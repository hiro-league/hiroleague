"""The app's copies of what the core keeps, kept fresh in one place (unified communication, phase 4).

An app keeps copies of three things the core owns: the family list (family.py), the AI profiles (llm/core_ai.py) and
the voice profiles (voices.py). Each reader says which resource it copies and how to read it again
(`link.follow(resource, refresh)`). One loop, owned by the link (hiroleague.py), reads a copy again:

- when the core says `resource.changed {resource}` for it (the one note, the same the phones get);
- when the link connects: events aren't queued, so whatever changed while the core was away is read then;
- every FOLLOW_EVERY seconds, all of them: a slow safety net for a change that sends no note (one made with the core's
  command line, which runs in a process of its own) and for a note lost on the way (Michel, Nov 24: Q9).

One bad read never stops the others or the loop: it is logged, and the next note, connect or round tries again.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from .errors import failed

FOLLOW_EVERY = 1800.0  # seconds: the safety net's round, for every copy

Refresh = Callable[[], Awaitable[Any]]


class Follower:
    """Reads the app's copies again when they are stale. `connected` says whether the core can be asked now."""

    def __init__(self, connected: Callable[[], bool], log: logging.Logger) -> None:
        self._connected = connected
        self._log = log
        self._refresh: dict[str, Refresh] = {}
        self._stale: set[str] = set()
        self._due: asyncio.Event | None = None

    def follow(self, resource: str, refresh: Refresh) -> Callable[[], None]:
        """Keep `resource` fresh with `refresh()`; read it as soon as possible. Returns the function that stops it."""
        self._refresh[resource] = refresh
        self._mark({resource})

        def unfollow() -> None:
            if self._refresh.get(resource) is refresh:
                del self._refresh[resource]
                self._stale.discard(resource)

        return unfollow

    def connected(self) -> None:
        """The link connected: every copy is read again (what changed while away sent no note we heard)."""
        self.all_again()

    def all_again(self) -> None:
        """Every copy is read again: the link connected, or the owner changed what the app is approved for (a read
        the core refused before may be answered now)."""
        self._mark(set(self._refresh))

    async def changed(self, _event: str, data: dict[str, Any]) -> None:
        """The core's `resource.changed`: read that copy again, if the app keeps one."""
        resource = str(data.get("resource") or "")
        if resource in self._refresh:
            self._log.debug("HiroLeague says %s changed", resource, extra={"resource": resource})
            self._mark({resource})

    def _mark(self, resources: set[str]) -> None:
        self._stale |= resources
        if self._due is not None and self._stale:
            self._due.set()

    async def run(self) -> None:
        """The one loop: a note, a connect or the round wakes it; it reads every stale copy, one after another."""
        self._due = asyncio.Event()
        if self._stale:
            self._due.set()
        while True:
            with suppress(TimeoutError):
                await asyncio.wait_for(self._due.wait(), FOLLOW_EVERY)
            if not self._due.is_set():  # the round: every copy
                self._stale |= set(self._refresh)
            self._due.clear()
            if not self._connected():
                continue  # the copies stay as they are; the next connect reads them all
            for resource in sorted(self._stale):
                self._stale.discard(resource)
                refresh = self._refresh.get(resource)
                if refresh is None:
                    continue
                try:
                    await refresh()
                except Exception as exc:  # one bad read never stops the others; logged, read again next time
                    failed(self._log, f"HiroLeague: reading {resource} again", exc)
