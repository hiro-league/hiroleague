"""ChannelEventHandler — dispatches infrastructure-level channel.event signals.

Handles raw dict events emitted by channel plugins via the channel.event
JSON-RPC method (e.g. pairing_request, gateway_connected). These are
infrastructure/security concerns that operate outside the UnifiedMessage
pipeline.

Distinct from EventHandler which handles application-level events carried
inside fully-validated UnifiedMessages (message_type == "event").
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from hiro_commons.log import Logger

log = Logger.get("CHEV")

ChannelEventHandlerFn = Callable[[dict[str, Any]], Awaitable[None]]


class ChannelEventHandler:
    """Dispatches channel-level infrastructure events to registered handlers.

    Usage::

        ch_event_handler = ChannelEventHandler()
        ch_event_handler.register("pairing_request", handle_pairing_request)
        ch_event_handler.register("gateway_connected", handle_gateway_connected)
        ch_event_handler.register("gateway_disconnected", handle_gateway_disconnected)

        channel_manager = ChannelManager(..., on_event=ch_event_handler.handle)

    Unregistered event types are logged and silently dropped.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, ChannelEventHandlerFn] = {}

    def register(self, event: str, handler: ChannelEventHandlerFn) -> None:
        """Register an async handler for the given channel event name."""
        self._handlers[event] = handler
        log.info("Registered channel event handler", event_type=event)

    async def handle(self, event: str, data: dict[str, Any]) -> None:
        """Dispatch a channel event to its registered handler."""
        handler = self._handlers.get(event)
        if handler is None:
            log.debug("No handler registered for channel event", event_type=event)
            return

        try:
            await handler(data)
        except Exception as exc:
            log.error(
                "Channel event handler error",
                event_type=event,
                error=str(exc),
                exc_info=True,
            )
