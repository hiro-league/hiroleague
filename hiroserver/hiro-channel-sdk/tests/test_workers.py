"""Background workers (hiro_channel_sdk/workers.py; Phase 9b: HomeHiro's copy moved here): tasks kept and awaited, loops that survive failures, and the
retry wait of `run()`, which starts over after a good run (B16)."""

import asyncio
import inspect
import logging

import pytest

from hiro_channel_sdk import workers
from hiro_channel_sdk.workers import Worker


def test_spawned_tasks_are_kept_logged_and_awaited_by_stop(caplog):
    ended: list[str] = []

    async def fails():
        raise RuntimeError("broken")

    async def forever():
        try:
            await asyncio.sleep(3600)
        finally:
            ended.append("forever")

    async def main():
        w = Worker()
        w.start()
        w.spawn(fails(), "fails")
        w.spawn(forever(), "forever")
        await asyncio.sleep(0.01)
        assert [t.get_name() for t in w._tasks] == ["worker-forever"]  # the failed one is gone...
        await w.stop()
        assert w._tasks == set() and not w.running

    with caplog.at_level(logging.ERROR, "hiro.workers"):
        asyncio.run(main())
    assert "worker-fails failed" in caplog.text  # ... and logged
    assert ended == ["forever"]  # stop() waited until it had ended


def test_every_rests_between_runs_and_survives_a_failure(caplog):
    runs: list[float] = []

    def tick():
        runs.append(asyncio.get_running_loop().time())
        if len(runs) == 2:
            raise ValueError("one bad run")

    async def main():
        w = Worker()
        w.start()
        w.every(0.05, tick, "tick", first_after=0.05)
        start = asyncio.get_running_loop().time()
        await asyncio.sleep(0.35)
        await w.stop()
        return start

    with caplog.at_level(logging.ERROR, "hiro.workers"):
        start = asyncio.run(main())
    assert len(runs) >= 4  # it went on after the failure
    # (margins: Windows timers are coarse)
    assert runs[0] - start >= 0.04
    assert all(b - a >= 0.04 for a, b in zip(runs, runs[1:], strict=False))
    assert "tick failed" in caplog.text


class Flaky(Worker):
    """run() fails at once, except the runs listed in `long_runs`, which last a while first."""

    retry_first, retry_most, good_after = 0.01, 0.04, 0.05

    def __init__(self, long_runs: set[int]) -> None:
        super().__init__()
        self.long_runs, self.runs, self.waits = long_runs, 0, []

    async def run(self) -> None:
        self.runs += 1
        if self.runs in self.long_runs:
            await asyncio.sleep(self.good_after * 1.5)  # (a margin: Windows timers are coarse)
        raise ConnectionError("dropped")

    def failed(self, exc: Exception, retry_in: float) -> None:
        self.waits.append(retry_in)


def run_until(worker: Flaky, runs: int) -> None:
    async def main():
        worker.start()
        for _ in range(400):
            if worker.runs >= runs:
                break
            await asyncio.sleep(0.005)
        await worker.stop()

    asyncio.run(main())


def test_run_is_retried_with_a_growing_wait():
    w = Flaky(long_runs=set())
    run_until(w, 5)
    assert w.waits[:4] == [0.01, 0.02, 0.04, 0.04]  # doubles, up to retry_most


def test_the_retry_wait_starts_over_after_a_good_run():
    """B16: the live HA connection waited 60 s before every reconnect once it had dropped a few times."""
    w = Flaky(long_runs={4})
    run_until(w, 6)
    assert w.waits[:5] == [0.01, 0.02, 0.04, 0.01, 0.02]


def test_start_twice_runs_once_and_a_restart_starts_over():
    starts: list[int] = []

    class Counting(Worker):
        def on_start(self) -> None:
            starts.append(1)
            self.spawn(asyncio.sleep(3600), "sleep")

    async def main():
        w = Counting()
        w.start()
        w.start()
        assert len(starts) == 1 and len(w._tasks) == 1
        w.restart()  # on the loop: at once
        await asyncio.sleep(0)
        assert len(starts) == 2 and w.running
        await w.stop()
        assert w._tasks == set()

    asyncio.run(main())


def test_stop_gives_up_on_a_task_that_will_not_end(monkeypatch, caplog):
    monkeypatch.setattr(workers, "STOP_TIMEOUT", 0.05)

    async def main():
        let_go = asyncio.Event()

        async def stubborn():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                await let_go.wait()  # cleaning up takes (too) long

        w = Worker()
        w.start()
        w.spawn(stubborn(), "stubborn")
        await asyncio.sleep(0)
        await w.stop()  # returns after STOP_TIMEOUT instead of hanging
        let_go.set()
        await asyncio.sleep(0.01)

    with caplog.at_level(logging.WARNING, "hiro.workers"):
        asyncio.run(asyncio.wait_for(main(), 2))
    assert "worker-stubborn still running" in caplog.text


def test_a_start_that_fails_can_be_tried_again():
    class Flaky(Worker):
        name = "flaky"
        fail = True

        def on_start(self) -> None:
            if self.fail:
                raise RuntimeError("database is not ready")

    async def main():
        w = Flaky()
        with pytest.raises(RuntimeError):
            w.start()
        assert not w.running  # else start() would never try again
        w.fail = False
        w.start()
        assert w.running
        await w.stop()

    asyncio.run(main())


def test_a_stop_that_fails_still_cancels_the_tasks(caplog):
    ended: list[str] = []

    class Stubborn(Worker):
        name = "stubborn"

        def on_stop(self) -> None:
            raise RuntimeError("the connection won't close")

    async def forever():
        try:
            await asyncio.sleep(3600)
        finally:
            ended.append("forever")

    async def main():
        w = Stubborn()
        w.start()
        w.spawn(forever(), "forever")
        await asyncio.sleep(0.01)
        await w.stop()

    with caplog.at_level(logging.ERROR, "hiro.workers"):
        asyncio.run(main())
    assert ended == ["forever"]
    assert "stubborn: stopping: RuntimeError: the connection won't close" in caplog.text
