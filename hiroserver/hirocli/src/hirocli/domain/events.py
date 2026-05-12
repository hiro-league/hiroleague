"""Domain event bus — single bridge between sync domain mutations and async runtime reactions.

Domain modules (``character``, ``conversation_channel``, ``preferences`` …) call
:func:`publish` from whatever thread happens to be writing the change (admin worker
threads, CLI sync code, the event loop itself). The bus owns the asyncio loop
captured at server startup and trampolines every dispatch onto that loop via
``call_soon_threadsafe``, so subscribers run as coroutines on the runtime's own
execution context — never on a worker thread without a loop.

This replaces the ad-hoc ``_*_SUBSCRIBERS`` lists that each domain module used
to maintain. One bus, one bridge, typed events.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

log = Logger.get("DOMAIN.BUS")


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


class DomainEventType:
    """String identifiers for domain events. Subscribers filter on these."""

    CHARACTER_CHANGED = "character.changed"
    CHARACTER_PHOTO_CHANGED = "character.photo_changed"
    CHANNEL_CHANGED = "channel.changed"
    PREFERENCES_SAVED = "preferences.saved"
    PROVIDERS_CHANGED = "providers.changed"


@dataclass(frozen=True)
class DomainEvent:
    """A single workspace-domain mutation ready for fan-out.

    ``workspace_path`` lets multi-workspace subscribers filter by scope.
    ``payload`` carries event-specific data (``character_id``, ``channel_id`` …).
    """

    type: str
    workspace_path: Path
    payload: dict[str, Any]


Handler = Callable[[DomainEvent], Awaitable[None]]


# ---------------------------------------------------------------------------
# Bus
# ---------------------------------------------------------------------------


class DomainEventBus:
    """Process-wide pub-sub for domain events.

    A single instance is created at server startup and exposed via
    :func:`get_domain_event_bus`. ``attach_loop`` is called once we're inside
    the server's event loop; from that point on, ``publish`` is safe from any
    thread and dispatches handlers on the captured loop.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subs: dict[str, list[Handler]] = defaultdict(list)

    # -- lifecycle --------------------------------------------------------

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the bus to the runtime event loop. Called once from server startup."""
        self._loop = loop

    def detach_loop(self) -> None:
        """Drop the loop reference (server shutdown). Subsequent publishes warn and drop."""
        self._loop = None

    def reset(self) -> None:
        """Clear subscribers and loop binding — for tests."""
        self._subs.clear()
        self._loop = None

    # -- subscription -----------------------------------------------------

    def subscribe(self, event_type: str, handler: Handler) -> None:
        if handler not in self._subs[event_type]:
            self._subs[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Handler) -> None:
        if handler in self._subs[event_type]:
            self._subs[event_type].remove(handler)

    # -- publish ----------------------------------------------------------

    def publish(self, event: DomainEvent) -> None:
        """Schedule fan-out of ``event`` onto the runtime loop. Thread-safe.

        Safe to call from any thread; handlers always run on the loop.
        Drops with a warning if the bus has no loop attached (startup race
        before ``attach_loop`` or after ``detach_loop``).
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            log.warning(
                "Domain event dropped — no loop attached",
                event_type=event.type,
                workspace=str(event.workspace_path),
            )
            return

        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None

        if current is loop:
            self._dispatch(event)
        else:
            loop.call_soon_threadsafe(self._dispatch, event)

    # -- internal --------------------------------------------------------

    def _dispatch(self, event: DomainEvent) -> None:
        handlers = list(self._subs.get(event.type, ()))
        if not handlers:
            log.debug("Domain event ignored (no subscribers)", event_type=event.type)
            return
        log.debug(
            "Domain event dispatched",
            event_type=event.type,
            subscriber_count=len(handlers),
        )
        for handler in handlers:
            asyncio.create_task(
                self._run_handler(handler, event),
                name=f"domain-event-{event.type}",
            )

    async def _run_handler(self, handler: Handler, event: DomainEvent) -> None:
        try:
            await handler(event)
        except Exception:
            log.error(
                "❌ Domain event handler failed",
                event_type=event.type,
                handler=getattr(handler, "__qualname__", repr(handler)),
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# Process-wide singleton accessor
# ---------------------------------------------------------------------------


_BUS = DomainEventBus()


def get_domain_event_bus() -> DomainEventBus:
    """Return the process-wide :class:`DomainEventBus` instance."""
    return _BUS
