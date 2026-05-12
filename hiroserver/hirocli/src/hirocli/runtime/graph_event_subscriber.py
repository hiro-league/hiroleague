"""GraphEventSubscriber — bridges agent-graph events to outbound side effects.

Replaces the post-adapt hook chain. Subscribers react to explicit domain
events emitted by graph nodes via ``StreamWriter``; ordering of subscribers
preserves the prior ordering guarantees (persist before mirror, etc.).

Each subscriber is a small async callable. The owner (CommManager) registers
them once and ``dispatch()`` runs them per event in the order they appear in
``_HANDLERS``.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from hiro_channel_sdk.constants import (
    CONTENT_TYPE_TEXT,
    EVENT_TYPE_MESSAGE_VOICED,
    MESSAGE_TYPE_EVENT,
)
from hiro_channel_sdk.log_scope_fields import (
    METADATA_LOG_REPLY_TO_MSG_ID,
    METADATA_LOG_TEXT_PREVIEW,
    METADATA_LOG_TRAFFIC_CLASS,
    METADATA_LOG_TRAFFIC_SUBCLASS,
    TRAFFIC_CLASS_OUTBOUND_LIFECYCLE,
    TRAFFIC_CLASS_OUTBOUND_REPLY,
    log_preview_snippet,
    unified_message_text_preview,
)
from hiro_channel_sdk.models import (
    ContentItem,
    EventPayload,
    MessageRouting,
    UnifiedMessage,
)
from hiro_commons.log import Logger

from .agent_graph import (
    GRAPH_ERROR,
    GRAPH_INGEST_COMPLETED,
    GRAPH_REPLY_COMPLETED,
    GRAPH_STT_COMPLETED,
    GRAPH_TTS_COMPLETED,
)
from .comm_log import LOG_OUT, comm_extras, comm_peer_label
from .envelope_factory import EnvelopeFactory

if TYPE_CHECKING:
    from .server_context import ServerContext

log = Logger.get("GRAPH_SUB")


# Per-event handler signature. ``inbound`` is the original UnifiedMessage that
# triggered the graph run (subscribers need it to preserve routing/metadata
# when building outbound envelopes). ``payload`` is the graph event payload.
EmitOutbound = Callable[[UnifiedMessage], Awaitable[None]]
Handler = Callable[
    [UnifiedMessage, dict[str, Any], EmitOutbound],
    Awaitable[None],
]


_FALLBACK_ERROR_BODY = (
    "Sorry, I encountered an error processing your message. Please try again."
)


class GraphEventSubscriber:
    """Routes graph events to outbound envelopes + storage side effects.

    Owned by ``CommunicationManager``. ``AgentManager`` calls
    :meth:`dispatch` for each event the graph emits.
    """

    def __init__(
        self,
        ctx: "ServerContext",
        emit_outbound: EmitOutbound,
    ) -> None:
        self._ctx = ctx
        self._emit = emit_outbound
        # Per-inbound state shared across events from the same graph run
        # (e.g. reply_id needed by the voiced subscriber when tts.completed
        # fires after reply.completed). Cleared when the graph finishes.
        self._run_state: dict[str, dict[str, Any]] = {}

        # Order matters: persist BEFORE mirror so the canonical row exists
        # before the broadcast goes out (matches prior PostAdaptHook order).
        self._handlers: dict[str, list[Handler]] = {
            GRAPH_INGEST_COMPLETED: [
                self._persist_inbound,
                self._mirror_user_message,
            ],
            # Persist transcript BEFORE emitting the live event so that any
            # device that reloads ``messages.history`` immediately after
            # receiving the live ``message.transcribed`` sees the same text.
            GRAPH_STT_COMPLETED: [
                self._persist_transcript,
                self._emit_transcribed,
            ],
            GRAPH_REPLY_COMPLETED: [
                self._persist_reply,
                self._emit_text_reply,
            ],
            GRAPH_TTS_COMPLETED: [self._emit_voiced],
            GRAPH_ERROR: [self._emit_error_fallback],
        }

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def begin_run(self, inbound_id: str) -> None:
        """Allocate per-run state. Called by ``AgentManager.handle``."""
        self._run_state.setdefault(inbound_id, {})

    def attach_persisted_event(
        self,
        inbound_id: str,
        event: asyncio.Event,
    ) -> None:
        """Register an ``asyncio.Event`` to set once inbound persistence finishes.

        Used by synthetic injectors (``message_send`` tool) that must block
        until the row is in the DB before returning their HTTP response.
        """
        self._run_state.setdefault(inbound_id, {})["persisted"] = event

    def end_run(self, inbound_id: str) -> None:
        """Drop per-run state once the graph finishes (success or failure)."""
        self._run_state.pop(inbound_id, None)

    async def dispatch(
        self,
        inbound: UnifiedMessage,
        event_name: str,
        payload: dict[str, Any],
    ) -> None:
        """Run all handlers registered for this event, in order."""
        handlers = self._handlers.get(event_name, [])
        if not handlers:
            return
        for handler in handlers:
            try:
                await handler(inbound, payload, self._emit)
            except Exception as exc:
                log.error(
                    "❌ subscriber %s — %s · failed",
                    handler.__name__, event_name,
                    error=str(exc), exc_info=True,
                )

    # ------------------------------------------------------------------
    # Handlers — keep tight, push complex work into domain modules.
    # ------------------------------------------------------------------

    async def _persist_inbound(
        self,
        inbound: UnifiedMessage,
        payload: dict[str, Any],
        emit: EmitOutbound,
    ) -> None:
        """Persist the inbound message + audio attachments. Non-fatal on error."""
        try:
            from ..domain.message_store import persist_inbound

            inbound_pk = await persist_inbound(self._ctx.workspace_path, inbound)
        except Exception as exc:
            log.warning(
                "⚠️ persist_inbound failed (non-fatal) — %s",
                comm_peer_label(inbound, self._ctx),
                error=str(exc),
            )
            return
        # Stash row PK + the text portion of the body so the STT subscriber
        # can backfill the transcript without losing any user-typed text.
        run = self._run_state.setdefault(payload.get("inbound_id", ""), {})
        run["inbound_msg_pk"] = int(inbound_pk)
        run["inbound_text_body"] = "\n".join(
            item.body for item in inbound.content
            if item.content_type == CONTENT_TYPE_TEXT and item.body
        )
        # Mark persistence done so synchronous senders (message_send tool)
        # can release as soon as the row is in the DB.
        evt: asyncio.Event | None = run.get("persisted")
        if evt is not None:
            evt.set()

    async def _mirror_user_message(
        self,
        inbound: UnifiedMessage,
        payload: dict[str, Any],
        emit: EmitOutbound,
    ) -> None:
        """Re-broadcast the inbound user message so all paired devices see it."""
        if inbound.routing.direction != "inbound":
            return
        mirror = EnvelopeFactory.user_message_mirror(inbound)
        await emit(mirror)
        log.info(
            f"{LOG_OUT} mirror — {comm_peer_label(mirror, self._ctx)}",
            **comm_extras(mirror, origin_msg_id=inbound.routing.id),
        )

    async def _persist_transcript(
        self,
        inbound: UnifiedMessage,
        payload: dict[str, Any],
        emit: EmitOutbound,
    ) -> None:
        """Backfill the persisted message body + attachment transcript metadata.

        Inbound persistence runs at ingest time, before STT, so the saved row
        has an empty body for audio-only messages. Once STT completes for a
        slot, we update both the attachment row's metadata and the message
        body so that any client reloading via ``messages.history`` (notably
        the admin UI, which has no live event channel) sees the transcript.
        """
        transcript = str(payload.get("transcript", ""))
        if not transcript:
            return
        item_index = payload.get("item_index")
        if not isinstance(item_index, int):
            return
        run = self._run_state.get(payload.get("inbound_id", ""), {})
        msg_pk = run.get("inbound_msg_pk")
        if not isinstance(msg_pk, int):
            return
        try:
            from ..domain.message_attachments import (
                list_attachments_for_message,
                update_attachment_metadata,
            )
            from ..domain.message_store import update_message_body

            await asyncio.to_thread(
                update_attachment_metadata,
                self._ctx.workspace_path,
                message_pk=msg_pk,
                slot_index=int(item_index),
                metadata_patch={"transcript": transcript},
            )
            attachments = await asyncio.to_thread(
                list_attachments_for_message,
                self._ctx.workspace_path,
                msg_pk,
            )
            transcript_parts: list[str] = []
            for att in sorted(attachments, key=lambda a: int(a["slot_index"])):
                meta = att.get("metadata") or {}
                t = meta.get("transcript") if isinstance(meta, dict) else None
                if isinstance(t, str) and t:
                    transcript_parts.append(t)
            text_body = run.get("inbound_text_body") or ""
            new_body = "\n".join(p for p in [text_body, *transcript_parts] if p)
            await update_message_body(self._ctx.workspace_path, msg_pk, new_body)
        except Exception as exc:
            log.warning(
                "⚠️ persist_transcript failed (non-fatal) — %s",
                comm_peer_label(inbound, self._ctx),
                error=str(exc),
            )

    async def _emit_transcribed(
        self,
        inbound: UnifiedMessage,
        payload: dict[str, Any],
        emit: EmitOutbound,
    ) -> None:
        """Forward each STT result as a ``message.transcribed`` event."""
        transcript = str(payload.get("transcript", ""))
        if not transcript.strip():
            log.warning(
                "⚠️ transcribed — %s · empty (silence?)",
                comm_peer_label(inbound, self._ctx),
            )
        event = EnvelopeFactory.transcript_event(inbound, transcript)
        await emit(event)
        log.info(
            f"{LOG_OUT} transcribed — {comm_peer_label(event, self._ctx)}",
            **comm_extras(event, ref_msg_id=inbound.routing.id),
        )

    async def _persist_reply(
        self,
        inbound: UnifiedMessage,
        payload: dict[str, Any],
        emit: EmitOutbound,
    ) -> None:
        """Save the agent text reply to ``data.db`` and stash its PK for TTS."""
        reply_id = str(payload.get("reply_id") or "")
        reply_text = str(payload.get("reply_text") or "")
        chat_channel_id = int(payload.get("chat_channel_id") or 0)
        if not reply_id or not reply_text or not chat_channel_id:
            return
        try:
            from ..domain.message_store import save_message

            reply_pk = await save_message(
                self._ctx.workspace_path,
                external_id=reply_id,
                channel_id=chat_channel_id,
                sender_type="agent",
                sender_id="server",
                content_type="text",
                body=reply_text,
            )
        except Exception as exc:
            log.warning(
                "⚠️ persist_reply failed (non-fatal) — %s",
                comm_peer_label(inbound, self._ctx),
                error=str(exc),
            )
            return
        # tts subscriber needs reply_pk to attach audio later.
        self._run_state.setdefault(payload.get("inbound_id", ""), {})["reply_pk"] = reply_pk

    async def _emit_text_reply(
        self,
        inbound: UnifiedMessage,
        payload: dict[str, Any],
        emit: EmitOutbound,
    ) -> None:
        """Build the outbound text reply envelope and enqueue it."""
        reply_text = str(payload.get("reply_text") or "")
        reply_id = str(payload.get("reply_id") or "")
        if not reply_text:
            return
        reply = _build_reply_envelope(inbound, reply_text, reply_id)
        await emit(reply)
        log.info(
            f"{LOG_OUT} reply — {comm_peer_label(reply, self._ctx)}",
            **comm_extras(reply, in_reply_to=inbound.routing.id),
        )

    async def _emit_voiced(
        self,
        inbound: UnifiedMessage,
        payload: dict[str, Any],
        emit: EmitOutbound,
    ) -> None:
        """Persist TTS audio attachment, then emit ``message.voiced`` event."""
        reply_id = str(payload.get("reply_id") or "")
        audio_b64 = str(payload.get("audio_b64") or "")
        media_type = str(payload.get("media_type") or "audio/mpeg")
        size = int(payload.get("size") or 0)
        duration_ms = payload.get("duration_ms")
        if not reply_id or not audio_b64 or size <= 0:
            return

        run = self._run_state.get(payload.get("inbound_id", ""), {})
        reply_pk = run.get("reply_pk")

        attachment_data: dict[str, Any] = {}
        if reply_pk is not None:
            attachment_data = await self._save_voice_attachment(
                inbound=inbound,
                reply_id=reply_id,
                reply_pk=int(reply_pk),
                chat_channel_id=int(payload.get("chat_channel_id") or 0),
                audio_b64=audio_b64,
                media_type=media_type,
                duration_ms=duration_ms,
                model=str(payload.get("model") or ""),
                voice=str(payload.get("voice") or ""),
            )

        voiced = _build_voiced_envelope(
            inbound=inbound,
            reply_id=reply_id,
            audio_b64=audio_b64,
            media_type=media_type,
            duration_ms=duration_ms,
            attachment_data=attachment_data,
        )
        await emit(voiced)
        log.info(
            f"{LOG_OUT} voiced — {comm_peer_label(voiced, self._ctx)}",
            **comm_extras(voiced, ref_id=reply_id, mime_type=media_type),
        )

    async def _emit_error_fallback(
        self,
        inbound: UnifiedMessage,
        payload: dict[str, Any],
        emit: EmitOutbound,
    ) -> None:
        """v1 fallback: when the LLM step fails, send a canned text reply once."""
        node = str(payload.get("node") or "")
        # Only LLM-stage failures should produce a user-visible canned reply.
        # STT/vision/tts errors are non-fatal and already logged by their nodes.
        if node not in {"call_model", "memory_out"}:
            return
        run = self._run_state.setdefault(payload.get("inbound_id", ""), {})
        if run.get("error_replied"):
            return
        run["error_replied"] = True
        reply = _build_reply_envelope(inbound, _FALLBACK_ERROR_BODY, "")
        await emit(reply)

    # ------------------------------------------------------------------
    # Voice attachment write — mirrors the prior AgentManager._synthesize_and_send
    # ------------------------------------------------------------------

    async def _save_voice_attachment(
        self,
        *,
        inbound: UnifiedMessage,
        reply_id: str,
        reply_pk: int,
        chat_channel_id: int,
        audio_b64: str,
        media_type: str,
        duration_ms: Any,
        model: str,
        voice: str,
    ) -> dict[str, Any]:
        try:
            from ..domain.blob_store import (
                DEFAULT_CHUNK_SIZE,
                blob_id_for_file,
                chunk_count_for_size,
            )
            from ..domain.data_store import data_dir
            from ..domain.media_store import (
                audio_extension_for_media_type,
                save_media_file,
            )
            from ..domain.message_attachments import attachment_ref, insert_attachment

            audio_bytes = base64.b64decode(audio_b64)
            ext = audio_extension_for_media_type(media_type)
            media_path = save_media_file(
                self._ctx.workspace_path,
                chat_channel_id,
                reply_pk,
                audio_bytes,
                ext,
                slot_index=0,
            )
            abs_path: Path = data_dir(self._ctx.workspace_path) / media_path
            blob_id = blob_id_for_file(abs_path)
            size = abs_path.stat().st_size
            ref = attachment_ref(reply_id, 0)
            insert_attachment(
                self._ctx.workspace_path,
                message_pk=reply_pk,
                slot_index=0,
                content_type="audio",
                blob_id=blob_id,
                media_type=media_type,
                size=size,
                media_path=media_path,
                filename=abs_path.name,
                duration_ms=int(duration_ms) if isinstance(duration_ms, (int, float)) else None,
                metadata={
                    "source": "character_tts",
                    "reply_to_message_id": inbound.routing.id,
                    "model": model,
                    "voice": voice,
                },
            )
            return {
                "blob_id": blob_id,
                "ref": ref,
                "size": size,
                "chunk_size": DEFAULT_CHUNK_SIZE,
                "chunk_count": chunk_count_for_size(size, DEFAULT_CHUNK_SIZE),
            }
        except Exception as exc:
            log.error(
                "❌ tts attachment skipped — %s · persistence_failed",
                comm_peer_label(inbound, self._ctx),
                error=str(exc), exc_info=True,
            )
            return {}


# ---------------------------------------------------------------------------
# Envelope builders (private to this module — they conserve the prior shapes)
# ---------------------------------------------------------------------------


def _build_reply_envelope(
    inbound: UnifiedMessage,
    body: str,
    reply_id: str,
) -> UnifiedMessage:
    meta = dict(inbound.routing.metadata or {})
    meta[METADATA_LOG_REPLY_TO_MSG_ID] = inbound.routing.id
    user_pv = unified_message_text_preview(inbound)
    if user_pv:
        meta[METADATA_LOG_TEXT_PREVIEW] = user_pv
    meta[METADATA_LOG_TRAFFIC_CLASS] = TRAFFIC_CLASS_OUTBOUND_REPLY
    meta[METADATA_LOG_TRAFFIC_SUBCLASS] = "text"
    routing_kwargs: dict[str, Any] = dict(
        channel=inbound.routing.channel,
        direction="outbound",
        sender_id="server",
        metadata=meta,
    )
    if reply_id:
        routing_kwargs["id"] = reply_id
    return UnifiedMessage(
        routing=MessageRouting(**routing_kwargs),
        content=[ContentItem(content_type="text", body=body)],
    )


def _build_voiced_envelope(
    *,
    inbound: UnifiedMessage,
    reply_id: str,
    audio_b64: str,
    media_type: str,
    duration_ms: Any,
    attachment_data: dict[str, Any],
) -> UnifiedMessage:
    meta = dict(inbound.routing.metadata or {})
    meta[METADATA_LOG_REPLY_TO_MSG_ID] = inbound.routing.id
    user_pv = unified_message_text_preview(inbound)
    meta[METADATA_LOG_TEXT_PREVIEW] = user_pv if user_pv else log_preview_snippet(reply_id)
    meta[METADATA_LOG_TRAFFIC_CLASS] = TRAFFIC_CLASS_OUTBOUND_LIFECYCLE
    meta[METADATA_LOG_TRAFFIC_SUBCLASS] = EVENT_TYPE_MESSAGE_VOICED
    return UnifiedMessage(
        message_type=MESSAGE_TYPE_EVENT,
        routing=MessageRouting(
            channel=inbound.routing.channel,
            direction="outbound",
            sender_id="server",
            metadata=meta,
        ),
        event=EventPayload(
            type=EVENT_TYPE_MESSAGE_VOICED,
            ref_id=reply_id,
            data={
                "audio": audio_b64,
                "mime_type": media_type,
                "duration_ms": duration_ms,
                **attachment_data,
            },
        ),
    )


# ``contextlib`` import is retained because this module may grow context
# managers in subsequent passes; flake8 ignores unused imports here, but the
# lint suppression is intentional to keep imports stable.
_ = contextlib  # pragma: no cover
