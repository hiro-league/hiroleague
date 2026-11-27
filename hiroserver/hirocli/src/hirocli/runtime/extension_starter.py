"""The extension manager's starter: the processes of the extensions the core starts (the channel plugins).

It starts a plugin with the extension socket's address, its key folder (``<workspace>/channels/<name>/``) and, in its
process's environment, the pairing code the manager made for it (never on its command line) and the variables its
catalog entry names; it ends an older process
of the same plugin by its recorded pid, and stops them all at shutdown. It never starts an app: an app starts itself.
Signing in, settings and frames are the manager's (extension_manager.py).

A plugin is a tree of processes: from a source checkout ``uv``, then a venv's launcher, then the real Python; installed,
an entry point's ``.exe``, then Python. Windows keeps only a parent pid, so once a launcher in the middle ends its
children can't be found from here. So a plugin is always ended as a tree, while the tree is whole; on Windows each is
held in a job that ends it with the server, however the server ends (a forced kill included); and the first start
ends any plugin of this workspace an earlier server left running, found by its ``--key-dir``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

import psutil

from hiro_channel_sdk.constants import ENV_PAIRING_CODE
from hiro_commons import logging_foundation
from hiro_commons.log import Logger
from hiro_commons.process import is_running, kill_process, read_channel_pid, remove_channel_pid, write_channel_pid
from hiro_commons.process_job import ProcessJob

from ..domain.channel_catalog import channel_env
from ..domain.channel_config import ChannelConfig

if TYPE_CHECKING:
    from .server_context import ServerContext

log = Logger.get("EXTENSIONS")

CHANNELS_DIR = "channels"


def key_dir(workspace_path: Path, name: str) -> Path:
    """A started extension's own folder: its key and the id the manager gave it (beside its descriptor)."""
    return workspace_path / CHANNELS_DIR / name


KEY_DIR_ARG = "--key-dir"
_END_WAIT_S = 5.0


def _start_process(
    cmd: list[str], env: dict[str, str], out: IO[str] | None, name: str
) -> tuple[subprocess.Popen[bytes], ProcessJob]:
    """Start a plugin's process on its own (a new process group, no window), its output into `out` (or nowhere), and
    hold its tree in a job (Windows) so it ends with the server."""
    target: Any = out if out is not None else subprocess.DEVNULL
    job = ProcessJob(f"the {name} extension")
    if sys.platform == "win32":
        proc = subprocess.Popen(
            cmd,
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW),
            close_fds=True,
            stdout=target,
            stderr=target,
            env=env,
        )
        # Held at once: a launcher starts its child only after loading, and what it starts then joins the job.
        job.hold(proc.pid)
        return proc, job
    return subprocess.Popen(cmd, start_new_session=True, close_fds=True, stdout=target, stderr=target, env=env), job


def _same_path(a: str, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def leftovers(channels_dir: Path, processes: Iterable[tuple[int, list[str] | None]]) -> list[int]:
    """The pids among `processes` (pid, command line) that are a plugin of this workspace: their ``--key-dir`` is a
    folder of `channels_dir`. Every process of a plugin's tree carries it (``uv``, the launcher, the real Python)."""
    found = []
    for pid, cmdline in processes:
        if not cmdline or KEY_DIR_ARG not in cmdline:
            continue
        at = cmdline.index(KEY_DIR_ARG) + 1
        if at < len(cmdline) and _same_path(str(Path(cmdline[at]).parent), channels_dir):
            found.append(pid)
    return found


def _running_processes() -> Iterable[tuple[int, list[str] | None]]:
    for p in psutil.process_iter(["pid", "cmdline"]):
        # cmdline is None for a process this user can't read (another user's, a system one): never ours.
        yield p.info["pid"], p.info["cmdline"]


class ExtensionStarter:
    """Starts and stops the processes of the extensions the core runs."""

    def __init__(self, ctx: ServerContext, socket_url: str) -> None:
        self._ctx = ctx
        self._socket_url = socket_url
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        # Each plugin's own output (its stdout and stderr, a crash's last words included): the server's child file
        # for it, server-channel-<name>-<day>.log in the logs folder, open while the plugin runs.
        self._outputs: dict[str, IO[str]] = {}
        self._jobs: dict[str, ProcessJob] = {}

    def running(self, name: str) -> bool:
        proc = self._processes.get(name)
        return proc is not None and proc.poll() is None

    def start(self, cfg: ChannelConfig, pairing_code: str) -> None:
        workspace = self._ctx.workspace_path
        folder = key_dir(workspace, cfg.name)
        folder.mkdir(parents=True, exist_ok=True)
        cmd = cfg.effective_command() + [
            "--hiro-ws", self._socket_url,
            "--key-dir", str(folder),
            "--log-dir", str(self._ctx.log_dir),
            "--log-level", self._ctx.config.log_level,
        ]
        # Its start environment: the server's, what its catalog entry sets (a library that reads the environment
        # before the plugin's own code runs), and its pairing code.
        env = {**os.environ, **channel_env(cfg.name), ENV_PAIRING_CODE: pairing_code}
        self.kill_previous(cfg.name)
        log.info(f"🔌 Starting extension — {cfg.name}", cmd=cmd)
        self._close_output(cfg.name)
        try:
            out = logging_foundation.child_log(f"channel-{cfg.name}")
        except RuntimeError as exc:  # the server's logging isn't set up (a test): the plugin's own file still has its lines
            log.debug("No file for the plugin's own output", channel=cfg.name, error=str(exc))
            out = None
        try:
            proc, job = _start_process(cmd, env, out, cfg.name)
        except FileNotFoundError:
            if out is not None:
                out.close()
            log.error(f"❌ Extension's command not found — {cfg.name}", cmd=cmd[0], hint=f"hiro extension install {cfg.name}")
            return
        except Exception as exc:
            if out is not None:
                out.close()
            log.error(f"❌ Couldn't start extension — {cfg.name}", error=str(exc), exc_info=True)
            return
        self._processes[cfg.name] = proc
        self._jobs[cfg.name] = job
        if out is not None:
            self._outputs[cfg.name] = out
        write_channel_pid(workspace, cfg.name, proc.pid)

    def kill_previous(self, name: str) -> None:
        pid = read_channel_pid(self._ctx.workspace_path, name)
        if pid is None:
            return
        if is_running(pid):
            log.info(f"Stopping the extension's previous process — {name}", pid=pid)
            kill_process(pid, include_tree=True)
        remove_channel_pid(self._ctx.workspace_path, name)

    def end_leftovers(self) -> None:
        """End every plugin of this workspace still running from an earlier server (one that crashed or was killed
        before it could stop them). Run before the first start, off the loop: it reads every process's command line."""
        channels = self._ctx.workspace_path / CHANNELS_DIR
        own = os.getpid()
        for pid in leftovers(channels, _running_processes()):
            if pid == own:
                continue
            log.warning("⚠️ Ending an extension process an earlier server left running", pid=pid)
            try:
                psutil.Process(pid).kill()
            except psutil.NoSuchProcess:  # its launcher's end took it already
                continue
            except psutil.AccessDenied as exc:
                log.warning("⚠️ Could not end a leftover extension process", pid=pid, error=str(exc))

    def terminate(self, name: str) -> None:
        """End a plugin's process tree: the one this server started, then any by its recorded pid (a previous
        server's)."""
        self._end(name, at_shutdown=False)
        pid = read_channel_pid(self._ctx.workspace_path, name)
        if pid is not None and is_running(pid):
            kill_process(pid, include_tree=True)
        remove_channel_pid(self._ctx.workspace_path, name)
        self._close_output(name)

    def stop_all(self) -> None:
        for name in list(self._processes):
            self._end(name, at_shutdown=True)
            remove_channel_pid(self._ctx.workspace_path, name)
        for name in list(self._outputs):
            self._close_output(name)

    def _end(self, name: str, *, at_shutdown: bool) -> None:
        """End the tree this server started for `name`. The tree first, while its launcher still links it (ending the
        launcher alone leaves the real Python running), then whatever is left in its job."""
        proc = self._processes.pop(name, None)
        job = self._jobs.pop(name, None)
        if proc is not None and proc.poll() is None:
            # A failed kill is not reported here: after its stop request the plugin often ends by itself just before
            # the kill reaches it. Only a process still running after the wait below is a problem.
            kill_process(proc.pid, include_tree=True)
        if job is not None:
            job.terminate()
        if proc is not None:
            try:
                proc.wait(timeout=_END_WAIT_S)
            except subprocess.TimeoutExpired:
                when = " at shutdown" if at_shutdown else ""
                log.warning(f"⚠️ Couldn't end the extension's process{when} — {name}", pid=proc.pid)

    def processes(self) -> list[tuple[str, subprocess.Popen[bytes]]]:
        return list(self._processes.items())

    def _close_output(self, name: str) -> None:
        out = self._outputs.pop(name, None)
        if out is not None:
            out.close()
