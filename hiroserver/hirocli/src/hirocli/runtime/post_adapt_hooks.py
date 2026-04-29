"""Post-adapt hooks — units of work that run after the MessageAdapterPipeline.

The router does NOT know about audio, persistence, or the inbound queue. It
just runs the adapter pipeline, then walks this hook chain. Each hook can
inspect the enriched message and emit zero or more outbound side-effect
messages via the ``emit`` callback.

Adding a new behaviour (e.g. an image-caption event, an audit log) means
appending one hook here and registering it in the bootstrap — no edits to
``CommunicationManager`` or ``MessageFlow``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Awaitable, Callable, Protocol

from hiro_channel_sdk.constants import CONTENT_TYPE_AUDIO
from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.log import Logger

from .comm_log import LOG_IN, LOG_OUT, comm_extras, comm_peer_label
from .envelope_factory import EnvelopeFactory

if TYPE_CHECKING:
    from .server_context import ServerContext

log = Logger.get("POST_ADAPT")


EmitOutbound = Callable[[UnifiedMessage], Awaitable[None]]


class PostAdaptHook(Protocol):
    """A unit of work that runs after the adapter pipeline.

    Receives the adapter-enriched message. May emit any number of outbound
    side-effect messages via ``emit``. Should not mutate ``msg``.
    """

    async def run(self, msg: UnifiedMessage, emit: EmitOutbound) -> None: ...


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------


class AdapterErrorLogHook:
    """Logs per-item ``adapter_error`` metadata that the pipeline left behind.

    Doesn't emit anything; pure observation. Comes first so the failure is
    visible before any other hook acts on the (possibly partially-enriched)
    message.
    """

    def __init__(self, ctx: ServerContext) -> None:
        self._ctx = ctx

    async def run(self, msg: UnifiedMessage, emit: EmitOutbound) -> None:
        for item in msg.content:
            if "adapter_error" in item.metadata:
                log.warning(
                    f"⚠️ {LOG_IN} Content item adaptation failed — {comm_peer_label(msg, self._ctx)}",
                    **comm_extras(
                        msg,
                        content_type=item.content_type,
                        error=item.metadata["adapter_error"],
                        msg_id=msg.routing.id,
                    ),
                )


class AudioTranscriptHook:
    """For each audio content item with a transcript, emit a ``message.transcribed`` event.

    This is the "modality mirror" the device uses to attach the transcript to
    the audio bubble. Empty transcripts (silence) still emit an event but log
    a warning so the silence is visible.
    """

    def __init__(self, ctx: ServerContext) -> None:
        self._ctx = ctx

    async def run(self, msg: UnifiedMessage, emit: EmitOutbound) -> None:
        for item in msg.content:
            if item.content_type != CONTENT_TYPE_AUDIO:
                continue
            transcript = item.metadata.get("description")
            if transcript is None:
                continue

            if not transcript.strip():
                log.warning(
                    f"⚠️ {LOG_IN} Empty audio transcription (silence?) — {comm_peer_label(msg, self._ctx)}",
                    **comm_extras(msg, msg_id=msg.routing.id),
                )

            event = EnvelopeFactory.transcript_event(msg, transcript)
            await emit(event)
            log.info(
                f"{LOG_OUT} Transcript event enqueued — {comm_peer_label(event, self._ctx)}",
                **comm_extras(
                    event,
                    ref_msg_id=msg.routing.id,
                    transcript_preview=transcript[:150],
                    transcript_len=len(transcript),
                ),
            )


class PersistenceHook:
    """Persist the inbound message to data.db (and any media files).

    Failure is logged but never propagated — persistence must not block agent
    delivery. This preserves the previous "non-fatal" behaviour of
    ``CommunicationManager._persist_inbound``.
    """

    def __init__(self, ctx: ServerContext) -> None:
        self._ctx = ctx

    async def run(self, msg: UnifiedMessage, emit: EmitOutbound) -> None:
        try:
            from ..domain.message_store import persist_inbound
            await persist_inbound(self._ctx.workspace_path, msg)
        except Exception as exc:
            log.warning(
                f"⚠️ {LOG_IN} Message persistence failed (non-fatal) — {comm_peer_label(msg, self._ctx)}",
                error=str(exc),
                msg_id=msg.routing.id,
            )


class InboundEnqueueHook:
    """Place the enriched message on the inbound queue for the AgentManager.

    Always runs last in the chain — once this fires, downstream consumers (the
    agent) will pick the message up.
    """

    def __init__(self, queue: asyncio.Queue[UnifiedMessage], ctx: ServerContext) -> None:
        self._queue = queue
        self._ctx = ctx

    async def run(self, msg: UnifiedMessage, emit: EmitOutbound) -> None:
        self._queue.put_nowait(msg)
        log.info(
            f"{LOG_IN} Queued after adaptation — {comm_peer_label(msg, self._ctx)}",
            **comm_extras(msg, msg_id=msg.routing.id, channel=msg.routing.channel),
        )
