"""Under WinSW, the server stops when the service's own WinSW is gone.

systemd and launchd stop a service's whole process tree. WinSW 2.12 has no job object: when WinSW itself dies (killed,
crashed), the server it started runs on, held by nothing, and keeps its ports and its PID file. The service manager
starts a new WinSW, whose server then finds "already running" and exits, again and again (seen Nov 25, 2026). So the
server watches the WinSW that started it (WinSW names its own path in ``WINSW_EXECUTABLE``) and stops cleanly when it
is gone; the new WinSW's server then starts.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import psutil
from hiro_commons.log import Logger

log = Logger.get("SERVER")

ENV_WINSW_EXECUTABLE = "WINSW_EXECUTABLE"  # set by WinSW for the program it starts (WinSWSystem.cs)
CHECK_EVERY_S = 5.0


def find_wrapper(environ: dict[str, str] | None = None) -> psutil.Process | None:
    """The WinSW among this process's ancestors (uv's launchers sit between), or None."""
    env = os.environ if environ is None else environ
    exe = env.get(ENV_WINSW_EXECUTABLE, "").strip()
    if not exe:
        return None
    wanted = os.path.normcase(str(Path(exe)))
    try:
        for parent in psutil.Process().parents():
            try:
                if os.path.normcase(parent.exe()) == wanted:
                    return parent
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue  # a launcher that ended or can't be read: look further up
    except psutil.Error:
        log.warning("⚠️ The service's WinSW can't be found among this server's parents", exc_info=True)
    return None


def is_alive(wrapper: psutil.Process) -> bool:
    # is_running() also compares the creation time, so a recycled PID doesn't count as the same WinSW.
    try:
        return wrapper.is_running() and wrapper.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


async def watch_service_wrapper(stop_event: asyncio.Event, *, every_s: float = CHECK_EVERY_S) -> None:
    """Stop the server (``stop_event``) once the WinSW that started it is gone; return when the server stops."""
    wrapper = await asyncio.to_thread(find_wrapper)
    if wrapper is None:
        log.warning(
            "⚠️ Running under WinSW but its process wasn't found: if WinSW dies, this server would outlive it",
            winsw=os.environ.get(ENV_WINSW_EXECUTABLE, ""),
        )
        return
    log.info("Watching the service's WinSW", pid=wrapper.pid)
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=every_s)
        except TimeoutError:
            pass
        if not stop_event.is_set() and not await asyncio.to_thread(is_alive, wrapper):
            log.warning(
                "⚠️ The service's WinSW is gone — stopping, so the service manager's new one can start this server",
                pid=wrapper.pid,
            )
            stop_event.set()
