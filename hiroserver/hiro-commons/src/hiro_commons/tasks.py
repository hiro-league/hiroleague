"""Background tasks nobody awaits, kept until they end, their failure logged.

    from hiro_commons import tasks
    tasks.keep(self._answer(conn, msg), name=f"extension-request-{msg.request_id}")

asyncio keeps only a weak reference to a task: one nobody holds can be collected before it ends, and its failure is
then said only when it is collected (if ever). `keep()` holds it until it ends and logs a failure at once, with its
traceback and the task's name. (ruff's RUF006 refuses a task nobody keeps.)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

log = logging.getLogger("hiro.tasks")
_kept: set[asyncio.Task[Any]] = set()


def keep(coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task[Any]:
    """Start `coro` as a task on the running loop, held until it ends; a failure is logged."""
    task = asyncio.get_running_loop().create_task(coro, name=name)
    _kept.add(task)
    task.add_done_callback(_ended)
    return task


def _ended(task: asyncio.Task[Any]) -> None:
    _kept.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("Background task %s failed: %s", task.get_name(), exc, exc_info=(type(exc), exc, exc.__traceback__),
                  extra={"task": task.get_name()})


def running() -> int:
    """How many kept tasks haven't ended (tests)."""
    return len(_kept)
