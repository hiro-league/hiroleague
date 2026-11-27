"""The core's own gateway (Hiro Gate relay) for device chat, run beside the server while Devices is on.

The gateway stays its own package and process (``hirogate``; the core already depends on it): this part only starts
``hirogate serve`` on 127.0.0.1 with this workspace's public key as its trust root, starts it again when it stops, and
stops it with the server. The devices channel connects to it (``Config.gateway_connect_url``); devices reach it by the
address they were given when they paired (``Config.gateway_url``: on a LAN server its LAN name, through Caddy). A
gateway run elsewhere is still possible: ``gateway_builtin: false`` and ``gateway_url`` set to it.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from typing import IO, TYPE_CHECKING, Any

from hiro_commons import logging_foundation
from hiro_commons.constants.network import DEFAULT_LOCALHOST
from hiro_commons.constants.storage import RUN_DIR
from hiro_commons.keys import public_key_to_b64
from hiro_commons.log import Logger
from hiro_commons.process import is_running, kill_process, read_pid, remove_pid, write_pid
from hiro_commons.process_job import ProcessJob

from hirocli.domain.features import feature_active

if TYPE_CHECKING:
    from hirocli.runtime.server_context import ServerContext

log = Logger.get("GATEWAY")

PID_FILENAME = f"{RUN_DIR}/gateway.pid"
STATE_DIR = "gateway"  # the gateway's own state file (desktop connected, last sign-in error), in the workspace
RESTART_FIRST_S = 1.0
RESTART_MAX_S = 60.0
STEADY_S = 60.0  # a gateway that ran this long before stopping starts again at once, not after the last delay


def gateway_command(ctx: ServerContext) -> list[str]:
    """``hirogate serve`` from the server's own environment, which has the gateway package (hirocli depends on it)."""
    return [
        sys.executable, "-m", "hirogateway.main", "serve",
        "--dir", str(ctx.workspace_path / STATE_DIR),
        "--desktop-pubkey", public_key_to_b64(ctx.desktop_private_key.public_key()),
        "--host", DEFAULT_LOCALHOST,
        "--port", str(ctx.config.gateway_port),
        "--log-dir", str(ctx.log_dir),
    ]


def _start(cmd: list[str], out: IO[str] | None) -> tuple[subprocess.Popen[bytes], ProcessJob]:
    """Start the gateway on its own (a new process group, no window), its output into `out` (or nowhere), and hold it
    in a job (Windows): ``sys.executable`` is a venv's launcher, and the real Python it starts would otherwise outlive
    a server that was killed."""
    target: Any = out if out is not None else subprocess.DEVNULL
    job = ProcessJob("the gateway")
    if sys.platform == "win32":
        proc = subprocess.Popen(
            cmd,
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW),
            close_fds=True,
            stdout=target,
            stderr=target,
        )
        job.hold(proc.pid)
        return proc, job
    return subprocess.Popen(cmd, start_new_session=True, close_fds=True, stdout=target, stderr=target), job


class BuiltinGateway:
    """Runs the core's gateway for as long as the server runs."""

    def __init__(self, ctx: ServerContext) -> None:
        self._ctx = ctx

    def wanted(self) -> bool:
        return feature_active("devices") and self._ctx.config.gateway_builtin

    async def run(self) -> None:
        if not self.wanted():
            log.debug("No built-in gateway: Devices is off, or the workspace uses a gateway run elsewhere")
            return
        self._stop_previous()
        delay = RESTART_FIRST_S
        while not self._ctx.stop_event.is_set():
            started = time.monotonic()
            code = await self._run_once()
            if self._ctx.stop_event.is_set():
                return
            if time.monotonic() - started >= STEADY_S:
                delay = RESTART_FIRST_S
            log.warning("⚠️ Gateway stopped; starting it again", exit_code=code, delay=f"{delay:.0f}s")
            try:
                await asyncio.wait_for(self._ctx.stop_event.wait(), timeout=delay)
                return
            except TimeoutError:
                pass
            delay = min(delay * 2, RESTART_MAX_S)

    async def _run_once(self) -> int | None:
        """Start the gateway and wait until it ends or the server stops; returns its exit code (None: stopped by us)."""
        cmd = gateway_command(self._ctx)
        try:
            out: IO[str] | None = logging_foundation.child_log("gateway")
        except RuntimeError:  # the server's logging isn't set up (a test): the gateway's own file still has its lines
            out = None
        try:
            proc, job = _start(cmd, out)
        except Exception:
            log.error("❌ Could not start the gateway", exc_info=True)
            if out is not None:
                out.close()
            return None
        write_pid(self._ctx.workspace_path, PID_FILENAME, proc.pid)
        log.info(
            f"✅ Gateway started on ws://{DEFAULT_LOCALHOST}:{self._ctx.config.gateway_port}",
            pid=proc.pid,
            devices_reach_it_at=self._ctx.config.gateway_url,
        )
        ended = asyncio.ensure_future(asyncio.to_thread(proc.wait))
        stopping = asyncio.ensure_future(self._ctx.stop_event.wait())
        try:
            await asyncio.wait({ended, stopping}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stopping.cancel()
            if not ended.done():
                self._stop(proc)
            job.terminate()  # the tree first (_stop), then anything of it left in its job
            if not ended.done():
                await asyncio.wait({ended}, timeout=5)
            remove_pid(self._ctx.workspace_path, PID_FILENAME)
            if out is not None:
                out.close()
        return proc.returncode if not self._ctx.stop_event.is_set() else None

    def _stop(self, proc: subprocess.Popen[bytes]) -> None:
        log.info("🛑 Stopping the gateway", pid=proc.pid)
        kill_process(proc.pid, include_tree=True)

    def _stop_previous(self) -> None:
        """A gateway left by a server that ended without stopping it would hold the port: stop it first."""
        pid = read_pid(self._ctx.workspace_path, PID_FILENAME)
        if pid is not None and is_running(pid):
            log.info("Stopping a gateway left by the last run", pid=pid)
            kill_process(pid, include_tree=True)
        remove_pid(self._ctx.workspace_path, PID_FILENAME)
