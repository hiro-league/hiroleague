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
                    ),
                )


class UserMessageMirrorHook:
    """Mirror inbound user ``message`` envelopes back out as a broadcast.

    Real device sends already fan out to sibling devices because the gateway
    broadcasts frames with no ``target_device_id``. In-process producers
    (admin / CLI / agent ``message_send`` tool) call
    ``CommunicationManager.receive`` directly and never traverse the gateway,
    so siblings never see the row live.

    This hook closes that gap by emitting a server-originated outbound
    ``message`` (no ``recipient_id`` ⇒ gateway broadcasts to every paired
    device) that preserves ``routing.id``. Devices upsert by id, so:

      - the originating device (when it exists) is excluded by the gateway's
        ``did != sender_id`` filter and never sees a duplicate of its own send;
      - sibling devices that received the live mirror **and** later see the row
        again on ``messages.history`` upsert on the same id (no duplicate);
      - devices that were offline at send time miss the live mirror but pick
        the row up from history catch-up at next gateway-connect.

    The hook runs after ``AudioTranscriptHook`` and ``PersistenceHook`` so the
    canonical ``created_at`` is already in the DB when the mirror flies out:
    that keeps the device-side row, the live-mirror row, and the future
    history-pull row all anchored to one persisted timestamp.
    """

    def __init__(self, ctx: ServerContext) -> None:
        self._ctx = ctx

    async def run(self, msg: UnifiedMessage, emit: EmitOutbound) -> None:
        if msg.routing.direction != "inbound":
            # Defensive: post-adapt hooks always see inbound messages today,
            # but keep the guard so a future re-entry from an outbound source
            # cannot loop on itself.
            return

        mirror = EnvelopeFactory.user_message_mirror(msg)
        await emit(mirror)
        log.info(
            f"{LOG_OUT} User message mirrored to paired devices — {comm_peer_label(mirror, self._ctx)}",
            **comm_extras(
                mirror,
                origin_msg_id=msg.routing.id,
                origin_sender_id=msg.routing.sender_id,
                content_types=[item.content_type for item in mirror.content],
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
                    **comm_extras(msg),
                )

            event = EnvelopeFactory.transcript_event(msg, transcript)
            await emit(event)
            log.info(
                f"{LOG_OUT} Transcript event enqueued — {comm_peer_label(event, self._ctx)}",
                **comm_extras(
                    event,
                    ref_msg_id=msg.routing.id,
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
        log.fineinfo(
            f"{LOG_IN} Queued after adaptation — {comm_peer_label(msg, self._ctx)}",
            **comm_extras(msg, channel=msg.routing.channel),
        )
