"""CommunicationManager — central message router for hirocli.

Responsibilities:
  - Receives inbound UnifiedMessages from all channel plugins (via ChannelManager's
    on_message callback) and routes them by message_type.
  - message_type "message": sends immediate ack event, spawns an adapter task
    that enriches the message concurrently then places it on the inbound queue.
  - message_type "request": dispatches to injected RequestHandler.
  - message_type "event": dispatches to injected EventHandler.
  - Unknown message_type: logs and enqueues an error response to the sender.
  - Monitors the outbound queue and routes each message to the correct channel
    plugin via ChannelManager.send_to_channel.
  - Performs permission checks (placeholder — to be implemented).

The adapter pipeline runs in an asyncio.Task per message so receive() always
returns immediately, never blocking other incoming messages regardless of how
long transcription or image analysis takes.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from hiro_channel_sdk.constants import (
    CONTENT_TYPE_AUDIO,
    CONTENT_TYPE_JSON,
    CONTENT_TYPE_TEXT,
    EVENT_TYPE_MESSAGE_RECEIVED,
    EVENT_TYPE_MESSAGE_TRANSCRIBED,
    MESSAGE_TYPE_EVENT,
    MESSAGE_TYPE_MESSAGE,
    MESSAGE_TYPE_REQUEST,
    MESSAGE_TYPE_RESPONSE,
)
from hiro_channel_sdk.models import (
    ContentItem,
    EventPayload,
    MessageRouting,
    UnifiedMessage,
)
from hiro_commons.log import Logger

if TYPE_CHECKING:
    from .channel_manager import ChannelManager
    from .event_handler import EventHandler
    from .message_adapter import MessageAdapterPipeline
    from .request_handler import RequestHandler
    from .server_context import ServerContext

log = Logger.get("COMM_MAN")

# Shared comm log fragments: one place for routing + content_hint so every COMM_MAN line
# stays scannable (direction, device, kind).
_LOG_IN = "⬇️"   # inbound (into hirocli)
_LOG_OUT = "⬆️"  # outbound (to channel / device)
_TEXT_SNIPPET_MAX = 120


def _parse_req_resp_body(msg: UnifiedMessage) -> dict[str, Any]:
    """Parse the first JSON content item for request/response detail fields."""
    for item in msg.content:
        if item.content_type == CONTENT_TYPE_JSON:
            try:
                return json.loads(item.body)
            except (json.JSONDecodeError, AttributeError):
                pass
    return {}


def _comm_kind(msg: UnifiedMessage) -> str:
    """Short type summary: message[text,audio], event:message.received, request:method, …"""
    mt = msg.message_type
    if mt == MESSAGE_TYPE_MESSAGE:
        if not msg.content:
            return "message[]"
        return f"message[{','.join(c.content_type for c in msg.content)}]"
    if mt == MESSAGE_TYPE_EVENT:
        et = msg.event.type if msg.event else "?"
        return f"event:{et}"
    if mt == MESSAGE_TYPE_REQUEST:
        method = _parse_req_resp_body(msg).get("method")
        return f"request:{method}" if method else "request"
    if mt == MESSAGE_TYPE_RESPONSE:
        status = _parse_req_resp_body(msg).get("status", "?")
        return f"response[{status}]"
    return str(mt)


def _snippet_text(body: str, max_len: int = _TEXT_SNIPPET_MAX) -> str:
    t = " ".join(body.split())
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _comm_content_hint(msg: UnifiedMessage) -> str | None:
    """Text snippet per item, or labels like audio/json/image for non-text bodies."""
    if msg.message_type != MESSAGE_TYPE_MESSAGE or not msg.content:
        return None
    parts: list[str] = []
    for item in msg.content:
        ct = item.content_type
        if ct == CONTENT_TYPE_TEXT:
            parts.append(_snippet_text(item.body) if item.body.strip() else "text:(empty)")
        elif ct == CONTENT_TYPE_AUDIO:
            parts.append("audio")
        elif ct == CONTENT_TYPE_JSON:
            parts.append(_snippet_text(item.body, 80) if item.body.strip() else "json:(empty)")
        else:
            parts.append(ct)
    return " | ".join(parts) if parts else None


def _req_resp_extras(msg: UnifiedMessage) -> dict[str, Any]:
    """Extract request/response-specific fields for log extras."""
    if msg.message_type not in (MESSAGE_TYPE_REQUEST, MESSAGE_TYPE_RESPONSE):
        return {}
    body = _parse_req_resp_body(msg)
    if not body:
        return {}
    out: dict[str, Any] = {}
    if msg.message_type == MESSAGE_TYPE_REQUEST:
        if "method" in body:
            out["method"] = body["method"]
        if body.get("params"):
            out["params"] = body["params"]
    else:
        if "status" in body:
            out["status"] = body["status"]
        if "error" in body:
            out["error"] = body["error"]
        if "data" in body:
            out["data"] = body["data"]
    return out


def _comm_extras(msg: UnifiedMessage, **kwargs: Any) -> dict[str, Any]:
    # Request/response details first, then content_hint, then caller fields.
    out: dict[str, Any] = {}
    rr = _req_resp_extras(msg)
    if rr:
        out.update(rr)
    hint = _comm_content_hint(msg)
    if hint:
        out["content_hint"] = hint
    out.update(kwargs)
    return out


def _check_permissions(msg: UnifiedMessage) -> None:
    """Placeholder for user/channel permission checks.

    Will enforce access control rules once the permission system is designed.
    Raise PermissionError to block the message.
    """


class CommunicationManager:
    """Routes messages between channel plugins and the application core.

    Usage::

        pipeline = MessageAdapterPipeline([AudioTranscriptionAdapter(), ...])
        event_handler = EventHandler()

        comm = CommunicationManager(
            ctx=ctx,
            adapter_pipeline=pipeline,
            event_handler=event_handler,
        )
        request_handler = RequestHandler(ctx, comm)
        comm.set_request_handler(request_handler)
        channel_manager = ChannelManager(ctx, ..., on_message=comm.receive)
        comm.set_channel_manager(channel_manager)

        await asyncio.gather(..., comm.run())
        await comm.enqueue_outbound(msg)
    """

    def __init__(
        self,
        ctx: ServerContext,
        adapter_pipeline: MessageAdapterPipeline | None = None,
        event_handler: EventHandler | None = None,
    ) -> None:
        self._ctx = ctx
        self._channel_manager: ChannelManager | None = None
        self._adapter_pipeline = adapter_pipeline
        self._request_handler: RequestHandler | None = None
        self._event_handler = event_handler
        self.inbound_queue: asyncio.Queue[UnifiedMessage] = asyncio.Queue()
        self.outbound_queue: asyncio.Queue[UnifiedMessage] = asyncio.Queue()

    def _peer_label(self, msg: UnifiedMessage) -> str:
        """Short peer label for logs: friendly name only when known, else device_id."""
        if msg.routing.direction == "outbound":
            device_id = (msg.routing.recipient_id or msg.routing.sender_id or "").strip()
        else:
            device_id = (msg.routing.sender_id or "").strip()

        meta = msg.routing.metadata or {}
        dn = meta.get("device_name")
        if isinstance(dn, str) and dn.strip():
            s = dn.strip()
            # Legacy "Name (device_id)" from older servers — drop id when it matches this peer.
            if device_id and s.endswith(f" ({device_id})"):
                return s[: -len(f" ({device_id})")]
            return s

        # Use the shared DeviceNameResolver from ServerContext instead of a private cache.
        return self._ctx.device_names.resolve(device_id)

    def _routing_tag(self, msg: UnifiedMessage) -> str:
        # Omit inbound/outbound here — ⬆️/⬇️ on the line already encode direction.
        return f"{self._peer_label(msg)} · {_comm_kind(msg)}"

    def set_channel_manager(self, channel_manager: ChannelManager) -> None:
        """Bind the ChannelManager after both objects have been constructed."""
        self._channel_manager = channel_manager

    def set_request_handler(self, handler: RequestHandler) -> None:
        """Bind the RequestHandler after both objects have been constructed."""
        self._request_handler = handler

    # ------------------------------------------------------------------
    # Inbound path  (channel plugin → hirocli core)
    # ------------------------------------------------------------------

    async def receive(self, data: dict[str, Any]) -> None:
        """Accept a raw params dict from ChannelManager's channel.receive handler.

        Validates it as a UnifiedMessage, runs the permission check, then
        routes by message_type. Returns immediately in all cases.
        """
        try:
            msg = UnifiedMessage.model_validate(data)
        except Exception as exc:
            log.warning(f"⚠️ {_LOG_IN} Dropping malformed message", error=str(exc))
            return

        try:
            _check_permissions(msg)
        except PermissionError as exc:
            log.warning(
                f"⚠️ {_LOG_IN} Blocked by permission — {self._routing_tag(msg)}",
                **_comm_extras(msg, channel=msg.routing.channel, error=str(exc)),
            )
            return

        match msg.message_type:
            case _ if msg.message_type == MESSAGE_TYPE_MESSAGE:
                await self._handle_message(msg)

            case _ if msg.message_type == MESSAGE_TYPE_REQUEST:
                if self._request_handler is not None:
                    asyncio.create_task(
                        self._safe_handle_request(msg),
                        name=f"request-{msg.routing.id}",
                    )
                else:
                    log.warning(
                        f"⚠️ {_LOG_IN} No RequestHandler, dropping — {self._routing_tag(msg)}",
                        **_comm_extras(msg, msg_id=msg.routing.id),
                    )

            case _ if msg.message_type == MESSAGE_TYPE_EVENT:
                if self._event_handler is not None:
                    asyncio.create_task(
                        self._safe_handle_event(msg),
                        name=f"event-{msg.routing.id}",
                    )
                else:
                    log.info(
                        f"{_LOG_IN} Event dropped (no EventHandler) — {self._routing_tag(msg)}",
                        msg_id=msg.routing.id,
                        event_type=msg.event.type if msg.event else None,
                    )

            case _:
                log.warning(
                    f"⚠️ {_LOG_IN} Unknown message_type, dropping — {self._routing_tag(msg)}",
                    **_comm_extras(msg, message_type=msg.message_type, msg_id=msg.routing.id),
                )
                await self._enqueue_error_response(
                    msg, f"Unknown message_type: {msg.message_type}"
                )

    async def _handle_message(self, msg: UnifiedMessage) -> None:
        """Ack immediately and spawn adapter pipeline as a background task."""
        await self._send_ack_event(msg)

        asyncio.create_task(
            self._adapt_and_queue(msg),
            name=f"adapt-{msg.routing.id}",
        )
        content_types = [item.content_type for item in msg.content]
        log.info(
            f"{_LOG_IN} Message acked, adapter spawned — {self._routing_tag(msg)}",
            **_comm_extras(
                msg,
                msg_id=msg.routing.id,
                channel=msg.routing.channel,
                content_types=content_types,
            ),
        )

    async def _adapt_and_queue(self, msg: UnifiedMessage) -> None:
        """Run the adapter pipeline then place the enriched message on inbound_queue."""
        device = msg.routing.metadata.get("device_name", msg.routing.sender_id)
        try:
            if self._adapter_pipeline is not None:
                msg = await self._adapter_pipeline.process(msg)

            for item in msg.content:
                if "adapter_error" in item.metadata:
                    log.warning(
                        f"⚠️ {_LOG_IN} Content item adaptation failed — {self._routing_tag(msg)}",
                        **_comm_extras(
                            msg,
                            content_type=item.content_type,
                            error=item.metadata["adapter_error"],
                            msg_id=msg.routing.id,
                        ),
                    )

                if item.content_type == "audio" and "description" in item.metadata:
                    transcript = item.metadata["description"]
                    if not transcript.strip():
                        log.warning(
                            f"⚠️ {_LOG_IN} Empty audio transcription (silence?) — {self._routing_tag(msg)}",
                            **_comm_extras(msg, msg_id=msg.routing.id),
                        )
                    transcript_event = UnifiedMessage(
                        message_type=MESSAGE_TYPE_EVENT,
                        routing=MessageRouting(
                            channel=msg.routing.channel,
                            direction="outbound",
                            sender_id="server",
                            recipient_id=msg.routing.sender_id,
                            metadata=msg.routing.metadata,
                        ),
                        event=EventPayload(
                            type=EVENT_TYPE_MESSAGE_TRANSCRIBED,
                            ref_id=msg.routing.id,
                            data={"transcript": transcript},
                        ),
                    )
                    await self.enqueue_outbound(transcript_event)
                    log.info(
                        f"{_LOG_OUT} Transcript event enqueued — {self._routing_tag(transcript_event)}",
                        **_comm_extras(
                            transcript_event,
                            ref_msg_id=msg.routing.id,
                            transcript_preview=transcript[:150],
                            transcript_len=len(transcript),
                        ),
                    )

            # Persist the inbound message to data.db before queuing for the agent.
            await self._persist_inbound(msg)

            self.inbound_queue.put_nowait(msg)
            log.info(
                f"{_LOG_IN} Queued after adaptation — {self._routing_tag(msg)}",
                **_comm_extras(msg, msg_id=msg.routing.id, channel=msg.routing.channel),
            )
        except Exception as exc:
            log.error(
                f"❌ {_LOG_IN} Adapter pipeline failed — {self._routing_tag(msg)}",
                **_comm_extras(msg, msg_id=msg.routing.id, error=str(exc)),
                exc_info=True,
            )
            await self._enqueue_error_response(msg, f"Adapter pipeline error: {exc}")

    async def _persist_inbound(self, msg: UnifiedMessage) -> None:
        """Save an inbound message to data.db and persist any media files."""
        try:
            from ..domain.message_store import persist_inbound
            await persist_inbound(self._ctx.workspace_path, msg)
        except Exception as exc:
            log.warning(
                f"⚠️ {_LOG_IN} Message persistence failed (non-fatal) — {self._routing_tag(msg)}",
                error=str(exc),
                msg_id=msg.routing.id,
            )

    async def _safe_handle_request(self, msg: UnifiedMessage) -> None:
        try:
            await self._request_handler.handle(msg)
        except Exception as exc:
            log.error(
                f"❌ {_LOG_IN} RequestHandler failed — {self._routing_tag(msg)}",
                **_comm_extras(msg, error=str(exc)),
                exc_info=True,
            )

    async def _safe_handle_event(self, msg: UnifiedMessage) -> None:
        try:
            await self._event_handler.handle(msg)
        except Exception as exc:
            log.error(
                f"❌ {_LOG_IN} EventHandler failed — {self._routing_tag(msg)}",
                **_comm_extras(msg, error=str(exc)),
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Ack / error helpers
    # ------------------------------------------------------------------

    async def _send_ack_event(self, msg: UnifiedMessage) -> None:
        """Send a message.received event back to the sender immediately."""
        ack = UnifiedMessage(
            message_type=MESSAGE_TYPE_EVENT,
            routing=MessageRouting(
                channel=msg.routing.channel,
                direction="outbound",
                sender_id="server",
                recipient_id=msg.routing.sender_id,
                metadata=msg.routing.metadata,
            ),
            event=EventPayload(
                type=EVENT_TYPE_MESSAGE_RECEIVED,
                ref_id=msg.routing.id,
            ),
        )
        await self.enqueue_outbound(ack)

    async def _enqueue_error_response(self, msg: UnifiedMessage, reason: str) -> None:
        """Enqueue an error response back to the sender."""
        body = json.dumps({"status": "error", "error": {"code": "routing_error", "message": reason}})
        error_msg = UnifiedMessage(
            message_type=MESSAGE_TYPE_RESPONSE,
            request_id=msg.request_id,
            routing=MessageRouting(
                channel=msg.routing.channel,
                direction="outbound",
                sender_id="server",
                recipient_id=msg.routing.sender_id,
                metadata=msg.routing.metadata,
            ),
            content=[ContentItem(content_type=CONTENT_TYPE_JSON, body=body)],
        )
        await self.enqueue_outbound(error_msg)

    # ------------------------------------------------------------------
    # Outbound path  (hirocli core → channel plugin)
    # ------------------------------------------------------------------

    async def enqueue_outbound(self, msg: UnifiedMessage) -> None:
        """Place a message on the outbound queue to be sent to its channel."""
        await self.outbound_queue.put(msg)
        log.info(
            f"{_LOG_OUT} Queued — {self._routing_tag(msg)}",
            **_comm_extras(msg, msg_id=msg.routing.id, channel=msg.routing.channel, items=len(msg.content)),
        )

    async def _outbound_worker(self) -> None:
        """Continuously drain the outbound queue and dispatch to channel plugins."""
        while True:
            msg = await self.outbound_queue.get()
            try:
                try:
                    _check_permissions(msg)
                except PermissionError as exc:
                    log.warning(
                        f"⚠️ {_LOG_OUT} Blocked by permission — {self._routing_tag(msg)}",
                        **_comm_extras(msg, channel=msg.routing.channel, error=str(exc)),
                    )
                    continue

                if self._channel_manager is None:
                    log.warning(
                        f"⚠️ {_LOG_OUT} Dropped (no ChannelManager) — {self._routing_tag(msg)}",
                        **_comm_extras(msg, msg_id=msg.routing.id),
                    )
                    continue

                log.info(
                    f"{_LOG_OUT} Dispatching — {self._routing_tag(msg)}",
                    **_comm_extras(msg, msg_id=msg.routing.id, channel=msg.routing.channel, items=len(msg.content)),
                )
                await self._channel_manager.send_to_channel(
                    msg.routing.channel, msg.model_dump(mode="json")
                )
            finally:
                self.outbound_queue.task_done()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the outbound worker. Add to asyncio.gather alongside ChannelManager."""
        log.info("✅ Communication Manager started")
        await self._outbound_worker()
