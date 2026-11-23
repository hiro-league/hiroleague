"""The extension manager's starter: the processes of the extensions the core starts (the channel plugins).

It starts a plugin with the extension socket's address, its key folder (``<workspace>/channels/<name>/``) and, in its
process's environment, the pairing code the manager made for it (never on its command line) and the variables its
catalog entry names; it ends an older process
of the same plugin by its recorded pid, and stops them all at shutdown. It never starts an app: an app starts itself.
Signing in, settings and frames are the manager's (extension_manager.py).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

from hiro_channel_sdk.constants import ENV_PAIRING_CODE
from hiro_commons import logging_foundation
from hiro_commons.log import Logger
from hiro_commons.process import is_running, kill_process, read_channel_pid, remove_channel_pid, write_channel_pid

from ..domain.channel_catalog import channel_env
from ..domain.channel_config import ChannelConfig

if TYPE_CHECKING:
    from .server_context import ServerContext

log = Logger.get("EXTENSIONS")

CHANNELS_DIR = "channels"


def key_dir(workspace_path: Path, name: str) -> Path:
    """A started extension's own folder: its key and the id the manager gave it (beside its descriptor)."""
    return workspace_path / CHANNELS_DIR / name


def _start_process(cmd: list[str], env: dict[str, str], out: IO[str] | None) -> subprocess.Popen[bytes]:
    """Start a plugin's process on its own (a new process group, no window), its output into `out` (or nowhere)."""
    target: Any = out if out is not None else subprocess.DEVNULL
    if sys.platform == "win32":
        return subprocess.Popen(
            cmd,
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW),
            close_fds=True,
            stdout=target,
            stderr=target,
            env=env,
        )
    return subprocess.Popen(cmd, start_new_session=True, close_fds=True, stdout=target, stderr=target, env=env)


class ExtensionStarter:
    """Starts and stops the processes of the extensions the core runs."""

    def __init__(self, ctx: ServerContext, socket_url: str) -> None:
        self._ctx = ctx
        self._socket_url = socket_url
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        # Each plugin's own output (its stdout and stderr, a crash's last words included): the server's child file
        # for it, server-channel-<name>-<day>.log in the logs folder, open while the plugin runs.
        self._outputs: dict[str, IO[str]] = {}

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
            proc = _start_process(cmd, env, out)
        except FileNotFoundError:
            if out is not None:
                out.close()
            log.error(f"❌ Extension's command not found — {cfg.name}", cmd=cmd[0], hint=f"hiro channel install {cfg.name}")
            return
        except Exception as exc:
            if out is not None:
                out.close()
            log.error(f"❌ Couldn't start extension — {cfg.name}", error=str(exc), exc_info=True)
            return
        self._processes[cfg.name] = proc
        if out is not None:
            self._outputs[cfg.name] = out
        write_channel_pid(workspace, cfg.name, proc.pid)

    def kill_previous(self, name: str) -> None:
        pid = read_channel_pid(self._ctx.workspace_path, name)
        if pid is None:
            return
        if is_running(pid):
            log.info(f"Stopping the extension's previous process — {name}", pid=pid)
            kill_process(pid)
        remove_channel_pid(self._ctx.workspace_path, name)

    def terminate(self, name: str) -> None:
        """End a plugin's process: the one this server started, then any by its recorded pid (a previous server's,
        or a ``uv`` launcher's child), as a tree."""
        proc = self._processes.pop(name, None)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError as exc:
                log.warning(f"⚠️ Couldn't end the extension's process — {name}", error=str(exc))
        pid = read_channel_pid(self._ctx.workspace_path, name)
        if pid is not None and is_running(pid):
            kill_process(pid, include_tree=True)
        remove_channel_pid(self._ctx.workspace_path, name)
        self._close_output(name)

    def stop_all(self) -> None:
        for name, proc in list(self._processes.items()):
            if proc.poll() is None:
                try:
                    proc.terminate()
                except OSError as exc:
                    log.warning(f"⚠️ Couldn't end the extension's process at shutdown — {name}", error=str(exc))
            remove_channel_pid(self._ctx.workspace_path, name)
        for name in list(self._outputs):
            self._close_output(name)

    def processes(self) -> list[tuple[str, subprocess.Popen[bytes]]]:
        return list(self._processes.items())

    def _close_output(self, name: str) -> None:
        out = self._outputs.pop(name, None)
        if out is not None:
            out.close()
