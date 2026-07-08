"""InboundPipeline — validate → permission → dispatch by message_type.

The Channel Manager's ``on_message`` callback lands here. ``receive()`` returns
immediately in all cases:

  - ``message`` → emits the immediate ``message.received`` ack, then hands
    the message to the AgentManager via the ``run_message`` callback.
  - ``request`` → dispatched to ``RequestHandler.handle`` in a background task;
    the returned response is enqueued by the task wrapper.
  - ``event``   → dispatched to ``EventHandler.handle`` in a background task.
  - unknown     → routing-error response is enqueued and the message is dropped.

The pipeline owns no message-flow state; the agent graph + outbound subscribers
own all post-validation work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable

from hiro_channel_sdk.constants import (
    MESSAGE_TYPE_EVENT,
    MESSAGE_TYPE_MESSAGE,
    MESSAGE_TYPE_REQUEST,
    MESSAGE_TYPE_STREAM,
)
from hiro_channel_sdk.log_scope_fields import unified_message_log_scope
from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.log import Logger, log_scope

from .comm_log import LOG_IN, comm_extras, comm_kind, comm_peer_label
from .envelope_factory import EnvelopeFactory

if TYPE_CHECKING:
    from .event_handler import EventHandler
    from .request_handler import RequestHandler
    from .server_context import ServerContext


log = Logger.get("INBOUND")


# Callback signature: dispatch a validated inbound ``message`` to the agent.
# Implemented by ``CommunicationManager._dispatch_to_agent``.
RunMessage = Callable[..., Awaitable[None]]
EmitOutbound = Callable[[UnifiedMessage], Awaitable[None]]


def _check_permissions(msg: UnifiedMessage) -> None:
    """Placeholder for inbound user/channel permission checks."""


def _ensure_conversation(ctx: "ServerContext", msg: UnifiedMessage) -> None:
    """Populate ``routing.metadata.chat_channel_id`` for channels that don't supply it.

    Device clients include ``chat_channel_id`` (they synced the conversation
    earlier). Channels like WhatsApp arrive with only a sender JID, so map
    ``(channel, sender_id)`` to a conversation here — mutating the shared ``msg``
    object *before* both persistence and agent dispatch read the key.
    """
    from ..domain.conversation_channel import (
        CHAT_CHANNEL_ID_METADATA_KEY,
        resolve_or_create_channel_for_sender,
    )

    if msg.message_type != MESSAGE_TYPE_MESSAGE:
        return
    meta = msg.routing.metadata
    if meta.get(CHAT_CHANNEL_ID_METADATA_KEY):
        return
    sender = msg.routing.sender_id
    if not sender:
        return
    conv = resolve_or_create_channel_for_sender(
        ctx.workspace_path, channel=msg.routing.channel, sender_id=sender,
    )
    meta[CHAT_CHANNEL_ID_METADATA_KEY] = conv.id


class InboundPipeline:
    """Routes inbound UnifiedMessages by ``message_type``."""

    def __init__(
        self,
        ctx: "ServerContext",
        run_message: RunMessage,
        emit_outbound: EmitOutbound,
        request_handler: "RequestHandler | None" = None,
        event_handler: "EventHandler | None" = None,
    ) -> None:
        self._ctx = ctx
        self._run_message = run_message
        self._emit = emit_outbound
        self._request_handler = request_handler
        self._event_handler = event_handler

    def _routing_tag(self, msg: UnifiedMessage) -> str:
        return f"{comm_peer_label(msg, self._ctx)} · {comm_kind(msg)}"

    async def receive(
        self,
        data: dict[str, Any],
        *,
        await_message_flow: bool = False,
    ) -> None:
        """Validate the raw dict, run permission check, and dispatch by type.

        ``await_message_flow=True`` blocks ``message`` payloads until the
        inbound-persistence subscriber finishes. Other message types ignore
        the flag.
        """
        try:
            msg = UnifiedMessage.model_validate(data)
        except Exception as exc:
            log.warning(f"⚠️ {LOG_IN} Dropping malformed message", error=str(exc))
            return

        try:
            _ensure_conversation(self._ctx, msg)
        except Exception as exc:
            # Without a resolved conversation the message can't be threaded/persisted.
            log.warning(
                f"⚠️ {LOG_IN} Could not resolve conversation — dropping",
                **comm_extras(msg, channel=msg.routing.channel, error=str(exc)),
            )
            return

        try:
            _check_permissions(msg)
        except PermissionError as exc:
            log.warning(
                f"⚠️ {LOG_IN} Blocked by permission — {self._routing_tag(msg)}",
                **comm_extras(msg, channel=msg.routing.channel, error=str(exc)),
            )
            return

        (
            _dev, _mid, _meth, _pv, _tc, _tsc,
        ) = unified_message_log_scope(msg, direction="inbound")
        with log_scope(
            device_id=_dev, msg_id=_mid, method=_meth,
            text_preview=_pv, traffic_class=_tc, traffic_subclass=_tsc,
        ):
            await self._dispatch(msg, await_message_flow=await_message_flow)

    async def _dispatch(
        self,
        msg: UnifiedMessage,
        *,
        await_message_flow: bool,
    ) -> None:
        match msg.message_type:
            case _ if msg.message_type == MESSAGE_TYPE_MESSAGE:
                # Immediate delivery ack so the device shows a tick before
                # the graph even starts.
                await self._emit(EnvelopeFactory.ack_event(msg))
                log.fineinfo(
                    f"{LOG_IN} message acked — {self._routing_tag(msg)}",
                    **comm_extras(msg, channel=msg.routing.channel),
                )
                await self._run_message(msg, await_persisted=await_message_flow)

            case _ if msg.message_type == MESSAGE_TYPE_REQUEST:
                await self._dispatch_request(msg)

            case _ if msg.message_type == MESSAGE_TYPE_STREAM:
                log.info(
                    f"{LOG_IN} stream frame ignored (download-only) — {self._routing_tag(msg)}",
                    **comm_extras(msg),
                )

            case _ if msg.message_type == MESSAGE_TYPE_EVENT:
                await self._dispatch_event(msg)

            case _:
                log.warning(
                    f"⚠️ {LOG_IN} Unknown message_type, dropping — {self._routing_tag(msg)}",
                    **comm_extras(msg, message_type=msg.message_type),
                )
                await self._emit(
                    EnvelopeFactory.routing_error_response(
                        msg, f"Unknown message_type: {msg.message_type}",
                    )
                )

    async def _dispatch_request(self, msg: UnifiedMessage) -> None:
        if self._request_handler is None:
            log.warning(
                f"⚠️ {LOG_IN} No RequestHandler, dropping — {self._routing_tag(msg)}",
                **comm_extras(msg),
            )
            return

        import asyncio
        asyncio.create_task(
            self._safe_handle_request(msg),
            name=f"request-{msg.routing.id}",
        )

    async def _safe_handle_request(self, msg: UnifiedMessage) -> None:
        try:
            response = await self._request_handler.handle(msg, emit_outbound=self._emit)
            if response is not None:
                await self._emit(response)
        except Exception as exc:
            log.error(
                f"❌ {LOG_IN} RequestHandler failed — {self._routing_tag(msg)}",
                **comm_extras(msg, error=str(exc)),
                exc_info=True,
            )

    async def _dispatch_event(self, msg: UnifiedMessage) -> None:
        if self._event_handler is None:
            log.info(
                f"{LOG_IN} Event dropped (no EventHandler) — {self._routing_tag(msg)}",
                event_type=msg.event.type if msg.event else None,
            )
            return

        import asyncio
        asyncio.create_task(
            self._safe_handle_event(msg),
            name=f"event-{msg.routing.id}",
        )

    async def _safe_handle_event(self, msg: UnifiedMessage) -> None:
        try:
            await self._event_handler.handle(msg)
        except Exception as exc:
            log.error(
                f"❌ {LOG_IN} EventHandler failed — {self._routing_tag(msg)}",
                **comm_extras(msg, error=str(exc)),
                exc_info=True,
            )
