"""The app's copies kept fresh in one place (follow.py, unified communication phase 4): the core's note, a connect and
the slow round each read the stale copies again, one bad read never stops the others, and nothing is read while the
core is away."""

import asyncio
import logging

from hiro_extension_kit import follow
from hiro_extension_kit.follow import Follower

log = logging.getLogger("testapp.hiroleague")


class Copies:
    """Three copies and the reads made of each."""

    def __init__(self) -> None:
        self.reads: list[str] = []
        self.failing: set[str] = set()

    def reader(self, resource: str):
        async def refresh() -> None:
            self.reads.append(resource)
            if resource in self.failing:
                raise RuntimeError(f"{resource} broke")

        return refresh


async def _until(predicate, seconds: float = 5.0) -> None:
    # Wait for the loop to have read, not a fixed sleep (a busy machine runs the loop late)
    for _ in range(int(seconds / 0.01)):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("not reached in time")


def _follower(connected: list[bool]) -> tuple[Follower, Copies]:
    copies = Copies()
    follower = Follower(lambda: connected[0], log)
    for resource in ("people", "ai.profiles", "voice.profiles"):
        follower.follow(resource, copies.reader(resource))
    return follower, copies


def test_each_copy_is_read_once_it_is_followed_then_on_its_note_and_all_on_a_connect():
    async def scenario() -> list[str]:
        follower, copies = _follower([True])
        loop = asyncio.create_task(follower.run())
        await _until(lambda: len(copies.reads) == 3)  # following one reads it as soon as possible
        await follower.changed("resource.changed", {"resource": "people", "reason": "people_changed"})
        await _until(lambda: len(copies.reads) == 4)
        await follower.changed("resource.changed", {"resource": "channels"})  # a copy the app doesn't keep
        follower.connected()
        await _until(lambda: len(copies.reads) == 7)
        await asyncio.sleep(0.05)  # nothing more comes
        loop.cancel()
        return copies.reads

    reads = asyncio.run(scenario())
    assert reads[3] == "people" and sorted(reads[4:]) == ["ai.profiles", "people", "voice.profiles"] and len(reads) == 7


def test_the_slow_round_reads_every_copy(monkeypatch):
    monkeypatch.setattr(follow, "FOLLOW_EVERY", 0.05)

    async def scenario() -> list[str]:
        follower, copies = _follower([True])
        loop = asyncio.create_task(follower.run())
        await _until(lambda: len(copies.reads) >= 6)  # the first reads, then a round with no note
        loop.cancel()
        return copies.reads

    reads = asyncio.run(scenario())
    assert sorted(reads[3:6]) == ["ai.profiles", "people", "voice.profiles"]


def test_nothing_is_read_while_the_core_is_away_and_all_is_read_on_connect():
    async def scenario() -> list[str]:
        connected = [False]
        follower, copies = _follower(connected)
        loop = asyncio.create_task(follower.run())
        await follower.changed("resource.changed", {"resource": "people"})
        await asyncio.sleep(0.05)
        assert copies.reads == []  # the copies stay as they are
        connected[0] = True
        follower.connected()
        await _until(lambda: len(copies.reads) == 3)
        loop.cancel()
        return copies.reads

    assert sorted(asyncio.run(scenario())) == ["ai.profiles", "people", "voice.profiles"]


def test_one_bad_read_is_logged_and_the_others_go_on(caplog):
    async def scenario() -> list[str]:
        follower, copies = _follower([True])
        copies.failing.add("ai.profiles")
        loop = asyncio.create_task(follower.run())
        await _until(lambda: len(copies.reads) == 3)
        copies.failing.clear()
        follower.connected()
        await _until(lambda: len(copies.reads) == 6)
        loop.cancel()
        return copies.reads

    with caplog.at_level(logging.WARNING, "testapp.hiroleague"):
        reads = asyncio.run(scenario())
    assert sorted(reads[:3]) == ["ai.profiles", "people", "voice.profiles"]
    [failed] = [r for r in caplog.records if "reading ai.profiles again" in r.getMessage()]
    assert failed.levelname == "ERROR" and "ai.profiles broke" in failed.getMessage()


def test_a_copy_no_longer_followed_is_not_read():
    async def scenario() -> list[str]:
        copies = Copies()
        follower = Follower(lambda: True, log)
        stop = follower.follow("people", copies.reader("people"))
        follower.follow("ai.profiles", copies.reader("ai.profiles"))
        stop()
        loop = asyncio.create_task(follower.run())
        await _until(lambda: len(copies.reads) == 1)
        await asyncio.sleep(0.05)
        loop.cancel()
        return copies.reads

    assert asyncio.run(scenario()) == ["ai.profiles"]
