"""Server process control and bootstrap helpers.

Pure domain logic — no Tool classes, no Console dependency.
Functions return structured data or raise on failure; the Tool and CLI
layers decide how to present results to the user.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME
from hiro_commons.constants.timing import DEFAULT_PING_INTERVAL_SECONDS
from hiro_commons.process import (
    find_workspace_root,
    is_running,
    read_pid,
    remove_pid,
    spawn_detached,
    stop_process,
    uv_python_cmd,
    wait_for_pid,
)

from ..autostart import (
    register_autostart,
    register_autostart_elevated,
    unregister_autostart,
    unregister_autostart_elevated,
)
from ..constants import ENV_ADMIN_UI, ENV_METRICS, ENV_WORKSPACE, ENV_WORKSPACE_PATH, PID_FILENAME
from ..domain.channel_config import ChannelConfig, load_channel_config, save_channel_config
from ..domain.config import Config, load_config, master_key_path
from ..domain.crypto import load_or_create_master_key
from ..domain.workspace import WorkspaceError, WorkspaceRegistry, create_workspace, resolve_workspace


# ---------------------------------------------------------------------------
# Server process control
# ---------------------------------------------------------------------------


def start_server(
    workspace_path: Path,
    config: Config,
    *,
    workspace_name: str,
    foreground: bool = False,
    admin: bool = False,
    metrics: bool = False,
) -> int | None:
    """Start the Hiro server for a workspace.

    Returns the child PID on success (``None`` for foreground mode, which
    blocks until the server exits).
    """
    load_or_create_master_key(workspace_path, filename=config.master_key_file)
    ensure_mandatory_devices_channel(workspace_path, config)

    pid = read_pid(workspace_path, PID_FILENAME)
    if pid and is_running(pid):
        return pid  # already running — caller decides what to tell the user

    if foreground:
        import asyncio as _asyncio

        from hirocli.runtime.server_process import _main

        try:
            _asyncio.run(
                _main(
                    foreground=True,
                    workspace_path=workspace_path,
                    workspace_name=workspace_name,
                    admin=admin,
                    metrics=metrics,
                )
            )
        except KeyboardInterrupt:
            pass
        return None

    # Background mode — clear stale PID so wait_for_pid starts clean.
    remove_pid(workspace_path, PID_FILENAME)

    script = str(Path(__file__).parents[1] / "runtime" / "server_process.py")
    env = {**os.environ, ENV_WORKSPACE_PATH: str(workspace_path), ENV_WORKSPACE: workspace_name}
    if admin:
        env[ENV_ADMIN_UI] = "1"
    if metrics:
        env[ENV_METRICS] = "1"

    stderr_log = workspace_path / "stderr.log"
    spawn_detached([*uv_python_cmd(), script], env=env, stderr_log=stderr_log)

    return wait_for_pid(workspace_path, PID_FILENAME, stderr_log=stderr_log)


def stop_server(workspace_path: Path) -> tuple[bool, int | None]:
    """Stop the server for a workspace.

    Returns ``(was_running, pid)``.
    """
    pid = read_pid(workspace_path, PID_FILENAME)
    if pid is None or not is_running(pid):
        remove_pid(workspace_path, PID_FILENAME)
        return False, pid

    config = load_config(workspace_path)
    if graceful_http_stop(config.http_port, pid, workspace_path):
        return True, pid

    stopped = stop_process(workspace_path, PID_FILENAME)
    return stopped, pid


def graceful_http_stop(http_port: int, pid: int, workspace_path: Path, timeout: float = 10.0) -> bool:
    """POST /_shutdown to the server and wait for the process to exit.

    Returns True if the process exited gracefully within the timeout.
    Avoids Windows ``taskkill /F`` which bypasses signal handlers and
    orphans channel-plugin subprocesses.
    """
    import time
    import urllib.request

    try:
        url = f"http://127.0.0.1:{http_port}/_shutdown"
        req = urllib.request.Request(url, method="POST", data=b"")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_running(pid):
            remove_pid(workspace_path, PID_FILENAME)
            return True
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------


def ensure_mandatory_devices_channel(workspace_path: Path, config: Config) -> None:
    """Create/update the mandatory ``devices`` channel config inside the workspace."""
    existing = load_channel_config(workspace_path, MANDATORY_CHANNEL_NAME)
    uv_workspace = find_workspace_root()
    # Installed packages should use the installed hiro-channel-devices executable,
    # not a stale dev workspace recorded by an earlier source checkout.
    workspace_dir = str(uv_workspace) if uv_workspace else ""
    channel_cfg = ChannelConfig(
        name=MANDATORY_CHANNEL_NAME,
        enabled=True,
        command=existing.command if existing and existing.command else [f"hiro-channel-{MANDATORY_CHANNEL_NAME}"],
        config={
            **(existing.config if existing else {}),
            "gateway_url": config.gateway_url,
            "device_id": config.device_id,
            "master_key_path": str(master_key_path(workspace_path, config)),
            "ping_interval": (
                existing.config.get("ping_interval", DEFAULT_PING_INTERVAL_SECONDS)
                if existing
                else DEFAULT_PING_INTERVAL_SECONDS
            ),
        },
        workspace_dir=workspace_dir,
    )
    save_channel_config(workspace_path, channel_cfg)


def ensure_default_preferences(workspace_path: Path) -> None:
    """Materialize ``preferences.json`` when missing (``load_preferences`` persists defaults)."""
    from ..domain.preferences import load_preferences, preferences_file

    if preferences_file(workspace_path).exists():
        return

    load_preferences(workspace_path)


# ---------------------------------------------------------------------------
# Workspace resolution
# ---------------------------------------------------------------------------


def resolve_or_create(workspace: str | None) -> tuple[Any, WorkspaceRegistry, Path]:
    """Resolve a workspace entry, auto-creating ``'default'`` if none exist."""
    try:
        entry, registry = resolve_workspace(workspace)
        return entry, registry, Path(entry.path)
    except WorkspaceError:
        if workspace is not None:
            raise
        entry, registry = create_workspace("default")
        return entry, registry, Path(entry.path)


# ---------------------------------------------------------------------------
# Autostart helpers
# ---------------------------------------------------------------------------


def register_autostart_for_workspace(workspace_id: str, elevated: bool) -> tuple[bool, str]:
    """Register auto-start using workspace id and return ``(success, method_label)``."""
    if elevated and sys.platform == "win32":
        try:
            accepted = register_autostart_elevated(workspace_id)
        except RuntimeError:
            accepted = False
        if accepted:
            return True, "elevated"
    try:
        method = register_autostart(workspace_id)
        return True, str(method)
    except (NotImplementedError, Exception):
        return False, "failed"


def unregister_autostart_for_workspace(workspace_id: str, stored_method: str | None) -> bool:
    """Unregister auto-start previously set up for a workspace."""
    if stored_method in (None, "skipped", "failed"):
        return False
    if stored_method == "elevated" and sys.platform == "win32":
        try:
            accepted = unregister_autostart_elevated(workspace_id)
        except RuntimeError:
            accepted = False
        if accepted:
            return True
    try:
        unregister_autostart(workspace_id)
        return True
    except (NotImplementedError, Exception):
        return False
