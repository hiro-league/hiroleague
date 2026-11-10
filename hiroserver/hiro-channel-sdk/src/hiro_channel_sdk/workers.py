"""Background work for an extension's app (Phase 9b): one `Worker` per service, started and stopped by the app.

HomeHiro's and StudyHiro's own copies became this one, so every extension runs background work the same way (and a
later job-status page can read it in one place). A worker keeps every task it starts, so none is lost or left running,
and no failure goes unlogged:
- `spawn(coro)`: a one-off task (a catch-up, a check); a failure is logged;
- `every(seconds, fn)`: `fn` again and again, resting `seconds` after each run; a failure is logged and the loop
  goes on;
- `run()`: override it for work that should always be running (a connection). When it fails, it is started again
  after a wait that doubles from `retry_first` up to `retry_most`, and starts over after a run that went well for
  `good_after` seconds. `wake()` ends the wait early (someone needs it now), but never sooner than `retry_first`
  after the failure.

`stop()` cancels them all and waits until they have ended. `restart()` is safe from any thread: a worker remembers
the event loop it started on.

How a failure is logged is the app's (`configure(failed=...)`): HomeHiro logs an expected error as one line and
anything else with its traceback. Without it, every failure is logged with its traceback.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable, Coroutine
from contextlib import suppress
from typing import Any

log = logging.getLogger("hiro.workers")

STOP_TIMEOUT = 5.0  # seconds stop() waits for cancelled tasks to end

FailedFn = Callable[[logging.Logger, str, BaseException], None]


def _log_failure(logger: logging.Logger, what: str, exc: BaseException) -> None:
    logger.error("%s: %s: %s", what, type(exc).__name__, exc, exc_info=exc)


_failed: FailedFn = _log_failure


def configure(*, failed: FailedFn | None = None) -> None:
    """Set how the app logs a worker's failure (once, at start; None puts the default back)."""
    global _failed
    _failed = failed or _log_failure


def report(what: str, exc: BaseException) -> None:
    """Log a worker's failure the app's way."""
    _failed(log, what, exc)


class Worker:
    name = "worker"
    retry_first, retry_most, good_after = 5.0, 60.0, 60.0

    def __init__(self) -> None:
        self.running = False
        self.problem: str | None = None  # the last failure, in words (for status pages)
        self.problem_at: float | None = None  # loop time of that failure
        self._tasks: set[asyncio.Task] = set()
        self._wake: asyncio.Event | None = None  # set while run() waits to be retried
        self.retry_at: float | None = None  # loop time of the next try, while waiting
        self._started_on: asyncio.AbstractEventLoop | None = None  # the loop it started on (restart() from other threads)

    # --- to override ---

    def on_start(self) -> None:
        """Set up and start tasks (on the event loop). Runs at every start."""

    def on_stop(self) -> None:
        """Clean up what isn't a task (a connection, a thread). Runs at every stop, before the tasks are cancelled."""

    async def run(self) -> None:
        """Work that should always be running; see the module's notes. Not used unless overridden."""

    def failed(self, exc: Exception, retry_in: float) -> None:
        """`run()` failed; it starts again in `retry_in` seconds. Override to react (keep the logging)."""
        report(f"{self.name} failed; retrying in {retry_in:.0f} s", exc)

    # --- lifecycle ---

    def start(self) -> None:
        if self.running:
            return
        with suppress(RuntimeError):  # (no running loop: a test starting it by hand)
            self._started_on = asyncio.get_running_loop()
        self.running = True
        try:
            self.on_start()
        except Exception:
            self.running = False  # else start() would never try again, and stop() would undo a start that never was
            raise
        if type(self).run is not Worker.run:
            self.spawn(self._keep_running(), "run")

    def cancel(self) -> None:
        """Stop without waiting for the tasks to end."""
        if self.running:
            self.running = False
            try:
                self.on_stop()
            except Exception as exc:  # the tasks must be cancelled all the same
                report(f"{self.name}: stopping", exc)
        for task in list(self._tasks):
            task.cancel()

    async def stop(self) -> None:
        tasks = list(self._tasks)
        self.cancel()
        if tasks:
            _done, left = await asyncio.wait(tasks, timeout=STOP_TIMEOUT)
            if left:
                log.warning("%s: %s still running after %.0f s", self.name, ", ".join(t.get_name() for t in left), STOP_TIMEOUT)

    def restart(self) -> None:
        """Stop and start again, e.g. after its settings changed. Safe from any thread (routes that are plain `def`
        run in one): it runs on the loop the worker started on."""
        try:
            here = asyncio.get_running_loop()
        except RuntimeError:
            here = None
        loop = self._started_on
        if loop is None or loop.is_closed() or here is loop:
            self._restart()
        else:
            loop.call_soon_threadsafe(self._restart)

    def _restart(self) -> None:
        self.cancel()
        try:
            self.start()
        except Exception as exc:  # it runs as a loop callback: nobody else would see it
            report(f"{self.name}: restarting", exc)

    # --- tasks ---

    def spawn(self, coro: Coroutine[Any, Any, Any], name: str | None = None) -> asyncio.Task:
        """Run `coro` as a task of this worker: kept until it ends, cancelled by stop(), failures logged."""
        task = asyncio.create_task(coro, name=f"{self.name}-{name}" if name else self.name)
        self._tasks.add(task)
        task.add_done_callback(self._ended)
        return task

    def _ended(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (exc := task.exception()):
            self._note(exc)
            report(f"{self.name}: {task.get_name()} failed", exc)

    def _note(self, exc: BaseException) -> None:
        self.problem = str(exc) or type(exc).__name__
        with suppress(RuntimeError):  # (no running loop: a test calling it directly)
            self.problem_at = asyncio.get_running_loop().time()

    def every(self, seconds: float, fn: Callable[[], Any], name: str, first_after: float = 0.0) -> asyncio.Task:
        """Run `fn` (plain or async) after `first_after` seconds, then again `seconds` after each run ends."""
        return self.spawn(self._every(seconds, fn, name, first_after), name)

    async def _every(self, seconds: float, fn: Callable[[], Any], name: str, first_after: float) -> None:
        await asyncio.sleep(first_after)
        while True:
            try:
                result = fn()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                self._note(exc)
                report(f"{self.name}: {name} failed", exc)
            await asyncio.sleep(seconds)

    def wake(self) -> None:
        """Retry run() now instead of at the end of its wait (at the earliest `retry_first` after it failed)."""
        if self._wake is not None:
            self._wake.set()

    async def _keep_running(self) -> None:
        wait = self.retry_first
        clock = asyncio.get_running_loop().time
        while True:
            started = clock()
            try:
                await self.run()
                error: Exception | None = None
            except Exception as exc:  # anything: it is retried
                error = exc
            if clock() - started >= self.good_after:
                wait = self.retry_first  # it ran well for a while: this is a fresh problem
            if error:
                self._note(error)
                try:
                    self.failed(error, wait)
                except Exception as exc:  # a failing hook must not end the retries (a connection would never come back)
                    report(f"{self.name}: reacting to its failure", exc)
            await self._pause(wait)
            wait = min(wait * 2, self.retry_most)

    async def _pause(self, wait: float) -> None:
        clock = asyncio.get_running_loop().time
        self.retry_at = clock() + wait
        self._wake = asyncio.Event()
        try:
            await asyncio.sleep(min(wait, self.retry_first))  # never sooner than this
            with suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), max(0.0, self.retry_at - clock()))
        finally:
            self._wake = self.retry_at = None
