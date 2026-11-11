"""Events: the bridge to the event loop, and the event bus features use to tell each other what happened.

FastAPI runs plain `def` routes in worker threads, and paho has threads of its own. Objects that belong
to the event loop (asyncio queues and tasks, and caches the loop reads) may only be touched from the loop
itself. `on_loop()` runs a function there: at once when already on the loop, otherwise as soon as the
loop is free.

`bus.publish(kind)` is safe from any thread: subscribers always run on the loop. Browser notices are
one subscriber (the app's /api/events route): every kind the app lists as a notice reaches every open page as
a Server-Sent Event. Which kinds are notices is the app's own list, next to that route.
"""

import asyncio
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from . import identity
from .errors import failed

log = identity.logger("events")

_loop: asyncio.AbstractEventLoop | None = None


def bind() -> None:
    """Remember the running loop. Called once at startup, on the loop."""
    global _loop
    _loop = asyncio.get_running_loop()


def on_loop(fn: Callable[..., Any], *args: Any) -> None:
    """Run `fn(*args)` on the event loop. Without a bound loop (tests, scripts) it runs at once."""
    try:
        here = asyncio.get_running_loop()
    except RuntimeError:
        here = None
    if _loop is None or _loop.is_closed() or here is _loop:
        fn(*args)
    else:
        _loop.call_soon_threadsafe(fn, *args)


Subscriber = Callable[[str, Any], None]


class EventBus:
    """Publish what happened; whoever cares subscribes. Subscribers get (kind, data), on the event loop,
    in the order they subscribed. One that fails is logged, and the others still hear the event."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Subscriber]] = defaultdict(list)

    def subscribe(self, kind: str, fn: Subscriber) -> Callable[[], None]:
        """Call `fn(kind, data)` for every `kind` published. Returns a function that unsubscribes."""
        self._subscribers[kind].append(fn)
        return lambda: self._subscribers[kind].remove(fn)

    def publish(self, kind: str, data: Any = None) -> None:
        """Tell the subscribers of `kind`. Safe from any thread."""
        on_loop(self._deliver, kind, data)

    def _deliver(self, kind: str, data: Any) -> None:
        for fn in list(self._subscribers.get(kind, ())):
            try:
                fn(kind, data)
            except Exception as exc:
                failed(log, f"A subscriber to {kind!r} ({getattr(fn, '__qualname__', fn)})", exc)


bus = EventBus()
