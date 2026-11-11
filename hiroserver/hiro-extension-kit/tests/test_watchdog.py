"""The event-loop watchdog (watchdog.py) names what blocked the loop, and stays quiet otherwise."""

import asyncio
import logging
import time

from hiro_extension_kit.watchdog import Watchdog


def hold_the_loop(seconds: float) -> None:
    time.sleep(seconds)  # what a slow database call or file write does to the loop


def test_a_blocked_loop_is_logged_with_where(caplog):
    async def main():
        dog = Watchdog(threshold=0.1, every=0.02)
        dog.start()
        await asyncio.sleep(0.05)
        hold_the_loop(0.4)
        await asyncio.sleep(0.1)
        await dog.stop()
        return dog

    with caplog.at_level(logging.WARNING, "testapp.watchdog"):
        dog = asyncio.run(main())
    assert len(dog.stalls) == 1
    stall = dog.stalls[0]
    assert 0.35 <= stall["seconds"] < 1.5
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
