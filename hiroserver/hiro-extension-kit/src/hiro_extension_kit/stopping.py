"""Hearing that the server was told to stop, before it waits for open requests.

uvicorn stops (Ctrl+C, SIGTERM, and --reload, which on Windows sends Ctrl+C) by first waiting for
every open request to end, and only then running the lifespan's shutdown. A request that never ends
by itself, a browser's /api/events stream, held that wait forever: in dev the backend stopped
answering after a file change until every tab of the app was closed (proven 2026-09-30).

`watch()` wraps uvicorn's own signal handlers, so the bus says "stopping" first and what must end
early (the app's open /api/events streams) ends then.
"""

import asyncio
import signal
import threading
from types import FrameType

from .events import bus

STOP_SIGNALS = [signal.SIGINT, signal.SIGTERM] + ([signal.SIGBREAK] if hasattr(signal, "SIGBREAK") else [])


def watch() -> None:
    """Call from the lifespan's start, on the event loop: uvicorn's handlers are in place by then."""
    if threading.current_thread() is not threading.main_thread():
        return  # signals reach only the main thread (the tests' app runs in another one)
    loop = asyncio.get_running_loop()
    for sig in STOP_SIGNALS:
        before = signal.getsignal(sig)
        if not callable(before):
            continue  # not uvicorn's: nothing to pass it on to

        def stopping(signum: int, frame: FrameType | None, before=before) -> None:
            # A signal handler interrupts whatever the loop was doing: hand over, don't run it here.
            loop.call_soon_threadsafe(bus.publish, "stopping")
            before(signum, frame)

        signal.signal(sig, stopping)
