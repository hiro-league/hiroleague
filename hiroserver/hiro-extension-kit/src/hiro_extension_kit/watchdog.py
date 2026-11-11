"""Finds what blocks the event loop.

While the loop runs one piece of code, it can't answer requests, its connections or open pages. A thread
asks the loop to answer every `EVERY` seconds. When it hasn't answered within `THRESHOLD`, the thread
reads where the loop's thread is at that moment (the app's own frames of its stack), waits until the
loop is back, and logs both: how long it was blocked, and where.

Always on: it costs one small callback a quarter second. `stalls` keeps the latest ones for /api/status.
"""

import asyncio
import sys
import threading
import time
import traceback
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from hiro_channel_sdk.workers import Worker

from . import identity

log = identity.logger("watchdog")

THRESHOLD = 0.5  # seconds without an answer that count as blocked
EVERY = 0.25  # seconds between asks
_OURS = identity.app().package  # the app's package folder


def where(frame) -> str:
    """The app's frames of a stack, innermost first: "streams.py:88 write ← streams.py:61 offer"."""
    stack = traceback.extract_stack(frame)
    ours = [f for f in stack if Path(f.filename).is_relative_to(_OURS) and Path(f.filename).name != "watchdog.py"]
    shown = (ours or stack)[-4:]
    return " ← ".join(f"{Path(f.filename).relative_to(_OURS) if Path(f.filename).is_relative_to(_OURS) else Path(f.filename).name}"
                      f":{f.lineno} {f.name}" for f in reversed(shown))


class Watchdog(Worker):
    name = "watchdog"

    def __init__(self, threshold: float = THRESHOLD, every: float = EVERY) -> None:
        super().__init__()
        self.threshold, self.interval = threshold, every
        self.stalls: deque[dict] = deque(maxlen=20)  # the latest: when, how long, where
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def on_start(self) -> None:
        loop = asyncio.get_running_loop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._watch, args=(loop, threading.get_ident()), name="loop-watchdog", daemon=True)
        self._thread.start()

    def on_stop(self) -> None:
        self._stop.set()

    def _watch(self, loop: asyncio.AbstractEventLoop, loop_thread: int) -> None:
        while not self._stop.wait(self.interval):
            answered = threading.Event()
            asked = time.monotonic()
            try:
                loop.call_soon_threadsafe(answered.set)
            except RuntimeError:  # the loop closed
                return
            if answered.wait(self.threshold):
                continue
            frame = sys._current_frames().get(loop_thread)
            at = where(frame) if frame else "?"
            while not answered.wait(1.0):
                if self._stop.is_set() or loop.is_closed():
                    return
            blocked = time.monotonic() - asked
            self.stalls.append({"at": datetime.now(UTC).isoformat(), "seconds": round(blocked, 2), "where": at})
            log.warning("Event loop blocked for %.1f s, at %s", blocked, at)


watchdog = Watchdog()
