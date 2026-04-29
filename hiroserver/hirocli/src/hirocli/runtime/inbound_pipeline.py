"""InboundPipeline — validate → permission → dispatch by message_type.

The Channel Manager's ``on_message`` callback lands here. ``receive()`` returns
immediately in all cases:

  - ``message`` → handed to ``MessageFlow.handle`` (which acks then forks).
  - ``request`` → handed to ``RequestHandler.handle`` in a background task;
    the returned response is enqueued by the task wrapper.
  - ``event``   → handed to ``EventHandler.handle`` in a background task.
  - unknown     → routing-error response is enqueued and the message is dropped.

The pipeline owns no state of its own — it's pure dispatch — so it's easy to
test with fakes for every collaborator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hiro_channel_sdk.constants import (
    MESSAGE_TYPE_EVENT,
    MESSAGE_TYPE_MESSAGE,
    MESSAGE_TYPE_REQUEST,
)
from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.log import Logger

from .comm_log import LOG_IN, comm_extras, comm_kind, comm_peer_label
from .envelope_factory import EnvelopeFactory
from .post_adapt_hooks import EmitOutbound

if TYPE_CHECKING:
    import asyncio

    from .event_handler import EventHandler
    from .message_flow import MessageFlow
    from .request_handler import RequestHandler
    from .server_context import ServerContext

log = Logger.get("INBOUND")


def _check_permissions(msg: UnifiedMessage) -> None:
    """Placeholder for inbound user/channel permission checks.

    Will enforce access control rules once the permission system is designed.
    Raise PermissionError to block the message.
    """


class InboundPipeline:
    """Routes inbound UnifiedMessages by ``message_type``."""

    def __init__(
        self,
        ctx: ServerContext,
        message_flow: MessageFlow,
        emit_outbound: EmitOutbound,
        request_handler: RequestHandler | None = None,
        event_handler: EventHandler | None = None,
    ) -> None:
        self._ctx = ctx
        self._message_flow = message_flow
        self._emit = emit_outbound
        self._request_handler = request_handler
        self._event_handler = event_handler

    def _routing_tag(self, msg: UnifiedMessage) -> str:
        # Direction arrow on the line already encodes inbound/outbound.
        return f"{comm_peer_label(msg, self._ctx)} · {comm_kind(msg)}"

    async def receive(self, data: dict[str, Any]) -> None:
        """Validate the raw dict, run permission check, and dispatch by type."""
        try:
            msg = UnifiedMessage.model_validate(data)
        except Exception as exc:
            log.warning(f"⚠️ {LOG_IN} Dropping malformed message", error=str(exc))
            return

        try:
            _check_permissions(msg)
        except PermissionError as exc:
            log.warning(
                f"⚠️ {LOG_IN} Blocked by permission — {self._routing_tag(msg)}",
                **comm_extras(msg, channel=msg.routing.channel, error=str(exc)),
            )
            return

        match msg.message_type:
            case _ if msg.message_type == MESSAGE_TYPE_MESSAGE:
                await self._message_flow.handle(msg)

            case _ if msg.message_type == MESSAGE_TYPE_REQUEST:
                await self._dispatch_request(msg)

            case _ if msg.message_type == MESSAGE_TYPE_EVENT:
                await self._dispatch_event(msg)

            case _:
                log.warning(
                    f"⚠️ {LOG_IN} Unknown message_type, dropping — {self._routing_tag(msg)}",
                    **comm_extras(msg, message_type=msg.message_type, msg_id=msg.routing.id),
                )
                await self._emit(
                    EnvelopeFactory.routing_error_response(
                        msg, f"Unknown message_type: {msg.message_type}"
                    )
                )

    async def _dispatch_request(self, msg: UnifiedMessage) -> None:
        if self._request_handler is None:
            log.warning(
                f"⚠️ {LOG_IN} No RequestHandler, dropping — {self._routing_tag(msg)}",
                **comm_extras(msg, msg_id=msg.routing.id),
            )
            return

        import asyncio  # local: avoid pulling asyncio when this branch is unused
        asyncio.create_task(
            self._safe_handle_request(msg),
            name=f"request-{msg.routing.id}",
        )

    async def _safe_handle_request(self, msg: UnifiedMessage) -> None:
        try:
            response = await self._request_handler.handle(msg)
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
                msg_id=msg.routing.id,
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
