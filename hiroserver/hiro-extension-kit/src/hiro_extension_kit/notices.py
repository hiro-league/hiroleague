"""The browsers' notices: what open pages are told over Server-Sent Events (/api/events), so they reload what they show.

Each app lists its own notices (the kinds its pages reload on, the same list as its frontend's live.ts) and may add to
the first message, "hello" (NetHiro and HomeHiro send their Home Assistant link's state with it):

    browsers = Browsers(NOTICES, hello=lambda: {"live": live.status()})
    router = events_router(browsers)

Backend kit, step 2: HomeHiro, NetHiro and TrainHiro each had a copy (live.py, events_api.py).
"""

import asyncio
import json
from collections.abc import Callable, Iterable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .events import EventBus, bus

PING_EVERY = 15  # seconds; the page reopens a stream that stays silent much longer


class Browsers:
    """Open /api/events streams; each gets every notice in `notices` published on the bus. The bus delivers on the
    event loop, which the queues belong to.

    When the server is told to stop (stopping.py), every stream ends: uvicorn waits for open requests before it stops,
    and a stream never ends by itself. The pages reconnect to the next server and reload what they show (its
    "hello")."""

    def __init__(self, notices: Iterable[str], *, hello: Callable[[], dict[str, Any]] | None = None,
                 events: EventBus = bus) -> None:
        self.notices = tuple(notices)
        self._hello = hello
        self._queues: set[asyncio.Queue] = set()
        self._stopping = False
        for kind in self.notices:
            events.subscribe(kind, self._notify)
        events.subscribe("stopping", self._stop)

    def _notify(self, kind: str, _data: object = None) -> None:
        for q in self._queues:
            q.put_nowait(kind)

    def _stop(self, _kind: str = "stopping", _data: object = None) -> None:
        self._stopping = True
        for q in self._queues:
            q.put_nowait(None)  # ends that stream

    async def stream(self, request: Request):
        q: asyncio.Queue = asyncio.Queue()
        self._queues.add(q)
        try:
            yield f"data: {json.dumps({'type': 'hello', **(self._hello() if self._hello else {})})}\n\n"
            while not self._stopping and not await request.is_disconnected():
                try:
                    kind = await asyncio.wait_for(q.get(), timeout=PING_EVERY)
                except TimeoutError:
                    # An event the page sees (a comment line would not): it keeps proxies from closing
                    # the stream, and tells the page the stream still works.
                    yield "event: ping\ndata: {}\n\n"
                    continue
                if kind is None:
                    return
                yield f"data: {json.dumps({'type': kind})}\n\n"
        finally:
            self._queues.discard(q)


def events_router(browsers: Browsers) -> APIRouter:
    """`GET /api/events` for these browsers."""
    router = APIRouter(prefix="/api")

    @router.get("/events")
    async def events(request: Request) -> StreamingResponse:
        """Server-Sent Events: 'hello' first, then the app's notices as data messages, and a 'ping' event every
        PING_EVERY seconds. Ends when the server stops."""
        return StreamingResponse(
            browsers.stream(request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
