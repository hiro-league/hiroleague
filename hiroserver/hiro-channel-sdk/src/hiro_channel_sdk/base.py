"""Abstract base class every channel plugin must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from .models import ChannelInfo, UnifiedMessage


class ChannelPlugin(ABC):
    """Contract between the Hiro server and a channel plugin.

    Subclass this, implement the abstract methods, then hand an instance to
    ``PluginTransport`` to connect it to the Hiro server.

    Lifecycle (called by PluginTransport):
      1. ``on_configure(config)`` — push credentials / settings from Hiro
      2. ``on_start()``           — begin listening for inbound messages
      3. ``on_stop()``            — graceful shutdown

    Sending / receiving:
      - Implement ``send(message)`` to translate an outbound UnifiedMessage
        into a third-party API call.
      - Call ``await self.emit(message)`` from within your implementation
        whenever an inbound message arrives; the transport forwards it to Hiro.
    """

    # Injected by PluginTransport — do not set manually.
    _emit_callback: Callable[[UnifiedMessage], Awaitable[None]] | None = None
    _event_callback: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None

    @property
    @abstractmethod
    def info(self) -> ChannelInfo:
        """Return channel name, version, and description."""

    @abstractmethod
    async def on_configure(self, config: dict[str, Any]) -> None:
        """Receive credentials and settings pushed by Hiro."""

    @abstractmethod
    async def on_start(self) -> None:
        """Begin polling / webhooks — start producing inbound messages."""

    @abstractmethod
    async def on_stop(self) -> None:
        """Gracefully tear down connections to the third party."""

    @abstractmethod
    async def send(self, message: UnifiedMessage) -> None:
        """Translate *message* into a third-party API call and dispatch it."""

    async def emit(self, message: UnifiedMessage) -> None:
        """Forward an inbound message from the third party to Hiro.

        Call this from your polling loop or webhook handler whenever a new
        message arrives from the external service.
        """
        if self._emit_callback is not None:
            await self._emit_callback(message)

    async def emit_event(self, event: str, data: dict[str, Any] | None = None) -> None:
        """Send a structured event back to Hiro (status, diagnostics, etc.)."""
        if self._event_callback is not None:
            await self._event_callback(event, data or {})

    async def on_event(self, event: str, data: dict[str, Any]) -> None:
        """Optional inbound event from Hiro to the plugin."""
        _ = (event, data)

    async def on_call(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Optional: answer a named request from Hiro (``channel.call``).

        Hiro waits for the answer, unlike ``send``. Return the result; raise to answer
        with an error (its message reaches the caller). A plugin that doesn't know
        ``name`` raises ``ChannelCallNotSupported``.
        """
        _ = params
        raise ChannelCallNotSupported(name)


class ChannelCallRefused(Exception):
    """An expected refusal from ``on_call`` (e.g. "WhatsApp isn't connected").

    Answered as an error carrying ``reason`` (a short code the caller can act on)
    and logged as a warning, not as a crash.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


class ChannelCallNotSupported(Exception):
    """The plugin has no ``channel.call`` of that name."""

    def __init__(self, name: str) -> None:
        super().__init__(f"This channel has no call named {name!r}")
        self.name = name
