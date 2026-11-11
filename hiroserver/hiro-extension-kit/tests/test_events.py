"""Other threads reaching the event loop (events.py): on_loop, the event bus, the browsers' notices (notices.py), and a
stop ending the browsers' streams (stopping.py).

FastAPI runs plain `def` routes in worker threads; what belongs to the event loop must still run there.
"""

import asyncio
import json
import signal
import threading

import pytest

from hiro_extension_kit import events as loop
from hiro_extension_kit import notices, stopping
from hiro_extension_kit.events import EventBus
from hiro_extension_kit.notices import Browsers


@pytest.fixture(autouse=True)
def unbound(monkeypatch):
    monkeypatch.setattr(loop, "_loop", None)  # each test binds its own loop; none is left behind


def from_a_worker_thread(fn):
    """Bind a loop, run fn() in a worker thread, let what it handed over run. Returns the loop's thread."""

    async def main():
        loop.bind()
        await asyncio.to_thread(fn)
        await asyncio.sleep(0.01)
        return threading.get_ident()

    return asyncio.run(main())


def test_on_loop_from_a_worker_thread_runs_on_the_loop():
    seen: list[int] = []
    loop_thread = from_a_worker_thread(lambda: loop.on_loop(lambda: seen.append(threading.get_ident())))
    assert seen == [loop_thread]


def test_on_loop_without_a_loop_runs_at_once():
    seen: list[int] = []
    loop.on_loop(seen.append, 1)
    assert seen == [1]


def test_a_notice_from_a_worker_thread_is_delivered_on_the_loop():
    """asyncio queues aren't thread-safe; a notice put from a worker thread often arrives anyway, which
    is why it went unnoticed. It must be put on the loop's own thread."""
    bus = EventBus()
    browsers = Browsers(["status"], events=bus)
    put_on: list[int] = []

    class Page(asyncio.Queue):
        def put_nowait(self, item):
            put_on.append(threading.get_ident())
            super().put_nowait(item)

    async def main():
        loop.bind()
        page = Page()
        browsers._queues.add(page)
        waiting = asyncio.create_task(page.get())
        await asyncio.sleep(0)
        await asyncio.to_thread(bus.publish, "status")
        return await asyncio.wait_for(waiting, 1), threading.get_ident()

    notice, loop_thread = asyncio.run(main())
    assert notice == "status" and put_on == [loop_thread]


def test_the_bus_delivers_on_the_loop_in_order_and_survives_a_failing_subscriber():
    bus = EventBus()
    heard: list[tuple[str, object, int]] = []

    def broken(_kind, _data):
        raise RuntimeError("a bug in one feature")

    bus.subscribe("synced", lambda kind, data: heard.append((kind, data, threading.get_ident())))
    bus.subscribe("synced", broken)
    unsubscribe = bus.subscribe("synced", lambda kind, data: heard.append(("second", data, threading.get_ident())))
    bus.subscribe("other", lambda kind, data: heard.append((kind, data, 0)))
    loop_thread = from_a_worker_thread(lambda: bus.publish("synced", {"areas": 2}))
    assert heard == [("synced", {"areas": 2}, loop_thread), ("second", {"areas": 2}, loop_thread)]
    unsubscribe()
    bus.publish("synced")  # no loop bound now: delivered at once
    assert heard[-1] == ("synced", None, threading.get_ident())
    assert len(heard) == 3


def test_every_notice_the_app_lists_reaches_open_pages_and_nothing_else():
    bus = EventBus()
    browsers = Browsers(["live", "status", "family"], events=bus)
    page: asyncio.Queue = asyncio.Queue()
    browsers._queues.add(page)
    for kind in ("live", "status", "family"):
        bus.publish(kind)
    bus.publish("not-a-notice")
    assert [page.get_nowait() for _ in range(page.qsize())] == ["live", "status", "family"]


class OpenPage:
    """The request of a page that stays open."""

    async def is_disconnected(self) -> bool:
        return False


def test_the_hello_carries_what_the_app_adds():
    browsers = Browsers(["logs"], hello=lambda: {"live": {"connected": True}}, events=EventBus())

    async def main():
        return await anext(browsers.stream(OpenPage()))  # type: ignore[arg-type]

    hello = asyncio.run(main())
    assert json.loads(hello.removeprefix("data: ")) == {"type": "hello", "live": {"connected": True}}


def test_a_stop_ends_every_open_stream():
    """uvicorn waits for open requests before it stops; a stream that never ends held a reload forever
    (the backend answered nothing until every tab was closed)."""
    bus = EventBus()
    browsers = Browsers(["logs"], events=bus)

    async def main():
        streams = [browsers.stream(OpenPage()) for _ in range(2)]  # type: ignore[arg-type]
        for s in streams:
            assert '"hello"' in await anext(s)
        waiting = [asyncio.create_task(anext(s)) for s in streams]
        await asyncio.sleep(0)
        bus.publish("stopping")
        for w in waiting:
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(w, 1)
        late = browsers.stream(OpenPage())  # type: ignore[arg-type]
        await anext(late)  # one opened while stopping gets its hello, then ends too
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(late), 1)
        return browsers._queues

    assert asyncio.run(main()) == set()


def test_a_quiet_stream_pings(monkeypatch):
    """A ping is an event the page sees: live.ts reopens a stream that went silent."""
    monkeypatch.setattr(notices, "PING_EVERY", 0.01)
    browsers = Browsers(["logs"], events=EventBus())

    async def main():
        s = browsers.stream(OpenPage())  # type: ignore[arg-type]
        await anext(s)
        return await asyncio.wait_for(anext(s), 1)

    assert asyncio.run(main()) == "event: ping\ndata: {}\n\n"


def test_a_stop_signal_says_stopping_then_reaches_uvicorn(monkeypatch):
    monkeypatch.setattr(stopping, "bus", bus := EventBus())
    heard: list[str] = []
    bus.subscribe("stopping", lambda kind, _data: heard.append(kind))
    uvicorn_got: list[int] = []
    before = {sig: signal.getsignal(sig) for sig in stopping.STOP_SIGNALS}

    async def main():
        loop.bind()
        for sig in stopping.STOP_SIGNALS:
            signal.signal(sig, lambda signum, _frame: uvicorn_got.append(signum))
        stopping.watch()
        handler = signal.getsignal(signal.SIGINT)
        assert callable(handler)
        handler(signal.SIGINT, None)
        assert uvicorn_got == [signal.SIGINT] and heard == []  # handed over, not run inside the handler
        await asyncio.sleep(0.01)

    try:
        asyncio.run(main())
    finally:
        for sig, handler in before.items():
            signal.signal(sig, handler)
    assert heard == ["stopping"]


def test_watching_outside_the_main_thread_changes_nothing():
    before = signal.getsignal(signal.SIGINT)

    async def main():
        stopping.watch()

    t = threading.Thread(target=asyncio.run, args=(main(),))  # a loop of its own, like the tests' app
    t.start()
    t.join()
    assert signal.getsignal(signal.SIGINT) is before
