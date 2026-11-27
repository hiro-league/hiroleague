"""Public service layer for hirogateway instance lifecycle management.

All real business logic lives here.  The CLI in main.py and external callers
(e.g. Hiro tools) both use these functions — no one reaches into main.py
internals directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from hiro_commons.keys import load_public_key_b64 as _load_public_key_b64
from hiro_commons.log import Logger
from hiro_commons.process import (
    is_running,
    read_pid,
    remove_pid,
    spawn_detached,
    stop_process,
    uv_python_cmd,
    wait_for_pid,
)

from .config import GatewayConfig, load_config, load_state, save_config
from .constants import PID_FILENAME
from .instance import (
    GatewayInstanceError,
    create_instance,
    load_registry,
    remove_instance,
    resolve_instance,
    set_default_instance,
)

log = Logger.get("GATEWAY")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class GatewaySetupResult:
    instance_name: str
    instance_path: str
    host: str
    port: int


@dataclass
class GatewayStartResult:
    instance_name: str
    already_running: bool
    pid: int | None
    host: str
    port: int


@dataclass
class GatewayStopResult:
    instance_name: str
    was_running: bool
    pid: int | None


@dataclass
class GatewayInstanceStatusEntry:
    name: str
    is_default: bool
    running: bool
    pid: int | None
    host: str
    port: int
    path: str
    desktop_connected: bool = False
    last_auth_error: str | None = None


@dataclass
class GatewayStatusResult:
    instances: list[GatewayInstanceStatusEntry] = field(default_factory=list)


@dataclass
class GatewayTeardownResult:
    instance_name: str
    instance_path: str
    stopped: bool
    purged: bool


# ---------------------------------------------------------------------------
# Config validation helpers
# ---------------------------------------------------------------------------


def _validate_desktop_public_key(key_b64: str) -> None:
    """Raise GatewayInstanceError if key_b64 is not a valid Ed25519 public key."""
    try:
        _load_public_key_b64(key_b64)
    except Exception as exc:
        raise GatewayInstanceError(
            f"Invalid desktop public key: {exc}. "
            "Provide the base64-encoded Ed25519 public key from 'hiro status'."
        ) from exc


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


def setup_instance(
    name: str,
    *,
    host: str,
    port: int,
    desktop_public_key: str,
    path: Path | None = None,
    log_dir: str = "",
    make_default: bool = False,
) -> GatewaySetupResult:
    """Create a new gateway instance and save its config."""
    # Validate before allocating the instance so a bad key leaves no partial state.
    _validate_desktop_public_key(desktop_public_key)

    entry, _ = create_instance(name, host=host, port=port, path=path)

    config = GatewayConfig(
        desktop_public_key=desktop_public_key,
        log_dir=log_dir,
    )
    save_config(Path(entry.path), config)

    if make_default:
        set_default_instance(name)

    return GatewaySetupResult(
        instance_name=entry.name,
        instance_path=entry.path,
        host=entry.host,
        port=entry.port,
    )


def start_instance(
    instance: str | None = None,
    *,
    verbose: bool = False,
) -> GatewayStartResult:
    """Start a gateway instance in the background.

    Waits for the child to write its PID file and confirm it is alive
    before returning, so the caller gets reliable feedback.
    """
    entry, _ = resolve_instance(instance)
    instance_path = Path(entry.path)

    config = load_config(instance_path)
    _validate_desktop_public_key(config.desktop_public_key)

    pid = read_pid(instance_path, PID_FILENAME)
    if pid and is_running(pid):
        return GatewayStartResult(
            instance_name=entry.name,
            already_running=True,
            pid=pid,
            host=entry.host,
            port=entry.port,
        )

    # Clear stale PID so wait_for_pid starts from a clean slate.
    remove_pid(instance_path, PID_FILENAME)

    cmd = [*uv_python_cmd(), "-m", "hirogateway.main", "start", "--instance", entry.name, "--foreground"]
    if verbose:
        cmd.append("--verbose")

    stderr_log = instance_path / "stderr.log"
    spawn_detached(cmd, stderr_log=stderr_log)

    # Wait for the child to write its own PID and confirm it is alive.
    child_pid = wait_for_pid(instance_path, PID_FILENAME, stderr_log=stderr_log)

    return GatewayStartResult(
        instance_name=entry.name,
        already_running=False,
        pid=child_pid,
        host=entry.host,
        port=entry.port,
    )


def stop_instance(instance: str | None = None) -> GatewayStopResult:
    """Stop a running gateway instance."""
    entry, _ = resolve_instance(instance)
    instance_path = Path(entry.path)

    pid = read_pid(instance_path, PID_FILENAME)
    was_running = pid is not None and is_running(pid)

    if was_running:
        stop_process(instance_path, PID_FILENAME)
    else:
        remove_pid(instance_path, PID_FILENAME)

    return GatewayStopResult(
        instance_name=entry.name,
        was_running=was_running,
        pid=pid,
    )


def get_status(instance: str | None = None) -> GatewayStatusResult:
    """Return running status for one or all gateway instances."""
    registry = load_registry()
    if not registry.instances:
        return GatewayStatusResult(instances=[])

    if instance is not None:
        if instance not in registry.instances:
            raise GatewayInstanceError(f"Gateway instance '{instance}' not found.")
        names = [instance]
    else:
        names = list(registry.instances.keys())

    entries = []
    for name in names:
        reg_entry = registry.instances[name]
        inst_path = Path(reg_entry.path)
        pid = read_pid(inst_path, PID_FILENAME)
        running = is_running(pid)
        state = load_state(inst_path)
        # If the process is no longer running, desktop_connected must be false
        # regardless of what state.json says (stale file from a crash).
        desktop_connected = running and state.desktop_connected
        entries.append(
            GatewayInstanceStatusEntry(
                name=name,
                is_default=(name == registry.default_instance),
                running=running,
                pid=pid,
                host=reg_entry.host,
                port=reg_entry.port,
                path=reg_entry.path,
                desktop_connected=desktop_connected,
                last_auth_error=state.last_auth_error if not desktop_connected else None,
            )
        )

    return GatewayStatusResult(instances=entries)


def teardown_instance(
    instance: str | None = None,
    *,
    purge: bool = False,
) -> GatewayTeardownResult:
    """Stop a gateway instance, and optionally purge its files."""
    entry, _ = resolve_instance(instance)
    instance_path = Path(entry.path)

    pid = read_pid(instance_path, PID_FILENAME)
    was_running = pid is not None and is_running(pid)
    stop_process(instance_path, PID_FILENAME)

    if purge:
        remove_instance(entry.name, purge=True)

    return GatewayTeardownResult(
        instance_name=entry.name,
        instance_path=entry.path,
        stopped=was_running,
        purged=purge,
    )
