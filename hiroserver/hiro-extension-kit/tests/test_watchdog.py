"""The event-loop watchdog (watchdog.py) names what blocked the loop, and stays quiet otherwise."""

import asyncio
import logging
import threading
import time

from hiro_extension_kit import watchdog as watchdog_module
from hiro_extension_kit.watchdog import Watchdog


def hold_the_loop(until: threading.Event) -> None:
    deadline = time.monotonic() + 10  # a broken watchdog fails the test instead of hanging it
    while not until.is_set() and time.monotonic() < deadline:  # what a slow database call or file write does to the loop
        time.sleep(0.005)


def test_a_blocked_loop_is_logged_with_where(monkeypatch, caplog):
    # The loop is held until the watchdog has read where it is, not for a fixed time: with every core busy (tests in
    # parallel) a 0.4 s hold could end before the watchdog's thread even ran (testing plan 1.2).
    seen, real_where = threading.Event(), watchdog_module.where

    def where(frame):
        at = real_where(frame)
        seen.set()
        return at

    monkeypatch.setattr(watchdog_module, "where", where)

    async def main():
        dog = Watchdog(threshold=0.1, every=0.02)
        dog.start()
        await asyncio.sleep(0)
        hold_the_loop(seen)
        for _ in range(500):  # the watchdog's thread notes the stall, then logs it, once the loop is back
            if "Event loop blocked" in caplog.text:
                break
            await asyncio.sleep(0.01)
        await dog.stop()
        return dog

    with caplog.at_level(logging.WARNING, "testapp.watchdog"):
        dog = asyncio.run(main())
    assert len(dog.stalls) == 1
    stall = dog.stalls[0]
    assert stall["seconds"] >= 0.1  # at least the threshold: the loop didn't answer within it
    assert "test_watchdog.py" in stall["where"] and "hold_the_loop" in stall["where"]
    assert "Event loop blocked" in caplog.text


def test_a_free_loop_is_not_logged():
    async def main():
        dog = Watchdog(threshold=0.1, every=0.02)
        dog.start()
        for _ in range(10):
            await asyncio.sleep(0.02)
        await dog.stop()
        return dog

    assert list(asyncio.run(main()).stalls) == []
