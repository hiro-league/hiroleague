"""Logging for one of the core's own processes besides the server: a channel plugin, the gateway."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from hiro_commons import logging_foundation
from hiro_commons.log import Logger


def init(
    component: str,
    log_dir: Path,
    *,
    level: str = "INFO",
    foreground: bool = False,
    module_log_levels: dict[str, str] | None = None,
) -> Path:
    """Start logging for one Hiro process on the logging foundation (hiro_commons.log: `Logger.start`).

    Parameters
    ----------
    component:
        The process's name: its daily file's stem (``channel-whatsapp-2026-11-20.jsonl``) and the source in each line,
        e.g. ``"gateway"``, ``"channel-devices"``, ``"channel-echo"``.
    log_dir:
        The folder its files are written in.  Created if absent.
    level:
        The core's level (``"INFO"``, ``"DEBUG"``, ``"FINEINFO"``…).
    foreground:
        If *True*, colourised lines are also written to the console.
        Use for ``hiro start --foreground`` and direct gateway runs.
    module_log_levels:
        Optional levels per area, e.g. ``{"AGENT": "DEBUG", "COMM": "WARNING"}``.

    Returns today's file.
    """
    Logger.set_level(level)
    if module_log_levels:
        Logger.set_module_levels(module_log_levels)
    return Logger.start(Path(log_dir), name=component, service=component, console=foreground)


def run(main: Coroutine[Any, Any, Any]) -> Any:
    """Run the process's main coroutine (``asyncio.run``) on a loop whose errors nobody could catch (a task that
    failed and was never awaited) land in the process's file."""

    async def watched() -> Any:
        logging_foundation.watch_loop()
        return await main

    return asyncio.run(watched())
