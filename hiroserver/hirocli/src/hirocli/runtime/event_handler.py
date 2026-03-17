"""EventHandler — handles inbound UnifiedMessages with message_type "event".

Application-level events (e.g. delivery receipts, device status updates)
arrive here after routing by CommunicationManager. Handlers are registered
per event type and invoked when a matching event arrives.

Distinct from ChannelEventHandler (infrastructure-level channel.event RPC
signals like pairing and connectivity). This handler operates on fully
validated UnifiedMessage objects.

Initial implementation: log all inbound events. Register handlers for
specific event types as the application grows.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.log import Logger

log = Logger.get("EVENT")

EventHandlerFn = Callable[[UnifiedMessage], Awaitable[None]]


class EventHandler:
    """Dispatches inbound event messages to registered per-type handlers.

    Usage::

        handler = EventHandler()
        handler.register("message.read", on_message_read)
        # wire into CommunicationManager at startup

    Event type is read from msg.event.type when present.
    Unregistered event types are logged and silently dropped.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, EventHandlerFn] = {}

    def register(self, event_type: str, handler: EventHandlerFn) -> None:
        """Register an async handler for the given event type."""
        self._handlers[event_type] = handler
        log.info("Registered event handler", event_type=event_type)

    async def handle(self, msg: UnifiedMessage) -> None:
        """Dispatch an inbound event message."""
        event_type = msg.event.type if msg.event else "<no-event-payload>"
        log.info(
            "Inbound event received",
            msg_id=msg.routing.id,
            channel=msg.routing.channel,
            sender=msg.routing.sender_id,
            event_type=event_type,
        )

        handler = self._handlers.get(event_type)
        if handler is None:
            return

        try:
            await handler(msg)
        except Exception as exc:
            log.error(
                "Event handler error",
                event_type=event_type,
                error=str(exc),
                exc_info=True,
            )
