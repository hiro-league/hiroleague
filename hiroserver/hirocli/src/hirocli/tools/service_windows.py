"""`hiro service` on Windows: the server as a Windows service under WinSW (``hiro_commons.winsw_service``).

Every operation but status needs an administrator; without one it raises ``NeedsAdminError`` with the exact command,
and the CLI asks for elevation (one UAC prompt) and runs it again.
"""

from __future__ import annotations

import dataclasses
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from hiro_commons.log import Logger
from hiro_commons.systemd_service import ServiceError
from hiro_commons.winsw_service import (
    NeedsAdminError,
    config_path,
    grant_read,
    install_service,
    is_admin,
    lock_file,
    lock_folder,
    lock_program_folder,
    remove_service,
    require_permissions_disk,
    require_windows,
    service_state,
    start_service,
    stop_service,
)

from .. import front_door_setup as door
from .. import linux_service as ls
from .. import windows_service as ws
from ..constants import ENV_CORE_NAME, ENV_DATA_DIR, ENV_SECRETS_FILE
from ..domain.front_door import ENV_FRONT_DOOR
from .service_models import ServiceControlResult, ServiceInstallResult, ServiceStatusResult, ServiceUninstallResult

log = Logger.get("TOOLS.SERVICE")


def command_line(action: str, *args: str) -> str:
    """The exact `hiro service ...` to run from an administrator terminal."""
    try:
        exe = ls.hiro_executable()
    except ServiceError:
        exe = "hiro"
    return subprocess.list2cmdline([exe, "service", action, *args])


def _options(workspace: str | None, **named: str | None) -> list[str]:
    out: list[str] = []
    for flag, value in named.items():
        if value:
            out += [f"--{flag.replace('_', '-')}", value]
    if workspace:
        out += ["--workspace", workspace]
    return out


def _config(name: str, binary_path: str) -> tuple[Path | None, dict[str, str], str | None]:
    """The service's WinSW configuration as registered: its path, its environment, its log folder."""
    wrapper = ws.exe_from_config(binary_path)
    if wrapper is None:
        return None, {}, None
    path = config_path(wrapper.parent, name)
    try:
        root = ET.parse(path).getroot()  # noqa: S314 — our own file, written by `hiro service install`
    except (OSError, ET.ParseError):
        # A service registered without its file (removed by hand): status still answers from the service manager.
        log.warning("⚠️ The service's WinSW configuration can't be read — HiroServer · service", path=str(path))
        return path, {}, None
    env = {e.get("name", ""): e.get("value", "") for e in root.findall("env")}
    return path, env, root.findtext("logpath")


def install(
    *,
    workspace: str | None = None,
    home: str | None = None,
    data_dir: str | None = None,
    source: str | None = None,
    core_name: str | None = None,
    **_: object,
) -> ServiceInstallResult:
    require_windows()
    lay = ws.layout(home, data_dir)
    name = ls.service_name(workspace)
    if not is_admin():
        raise NeedsAdminError(
            "Installing the HiroLeague service",
            command_line("install", *_options(workspace, home=home, data_dir=data_dir, source=source, name=core_name)),
        )
    require_permissions_disk(lay.home, "The Hiro home")
    require_permissions_disk(lay.data_dir, "The data folder")
    lay.home.mkdir(parents=True, exist_ok=True)
    lock_program_folder(lay.home)
    exe = ws.install_release(lay, source or ws.installed_package_spec())
    # The service core installs channels and apps' releases with uv, and has no PATH of the person's: without the
    # home's own copy, a channel installed before any app failed to find uv.
    ws.copy_uv_into(lay.home)
    spec = ws.build_spec(exe=exe, lay=lay, workspace=workspace)
    if core_name:
        spec = dataclasses.replace(spec, environment={**spec.environment, ENV_CORE_NAME: core_name})
    # The machine's front door, set up by the default service only (one per machine); its firewall rule for names
    # follows this release's Python.
    front = door.install_windows(lay.home, door.which_python(exe.parent.parent)) if not workspace else None
    if front is not None:
        spec = dataclasses.replace(spec, environment={**spec.environment, ENV_FRONT_DOOR: front.admin})
    install_service(spec, lay.service_dir)
    # The account exists from here on: it may read the program, and its data folder and secrets file are locked to it.
    grant_read(lay.home, service_id=name)
    lay.logs_dir.mkdir(parents=True, exist_ok=True)
    lock_folder(lay.data_dir, service_id=name, service_rights="M")
    secrets = lay.secrets_file(name)
    created = ws.write_secrets_file(secrets, ws.env_file_content(name))
    lock_file(secrets, service_id=name)
    start_service(name)
    log.info("✅ HiroLeague service installed and started — HiroServer · service", service=name, home=str(lay.home))
    return ServiceInstallResult(
        service=name,
        manager="winsw",
        user=spec.account,
        definition_path=str(config_path(lay.service_dir, name)),
        secrets_file=str(secrets),
        secrets_file_created=created,
        exec_start=subprocess.list2cmdline([str(exe), *spec.arguments]),
        started=True,
        edit_secrets=f'notepad "{secrets}"   (in an administrator terminal)',
        restart_command=f"Restart-Service {name}   (in an administrator PowerShell)",
        logs=str(lay.logs_dir),
        data_dir=str(lay.data_dir),
        front_door=front.service if front else None,
        front_door_account=front.account if front else None,
        firewall=front.firewall if front else [],
    )


def uninstall(*, workspace: str | None = None) -> ServiceUninstallResult:
    require_windows()
    name = ls.service_name(workspace)
    if not is_admin():
        raise NeedsAdminError("Removing the HiroLeague service", command_line("uninstall", *_options(workspace)))
    state = service_state(name)
    front_removed = door.uninstall_windows() if not workspace else False
    if not state.installed:
        return ServiceUninstallResult(service=name, removed=False, secrets_file=None, front_door_removed=front_removed)
    _, env, _ = _config(name, state.binary_path)
    remove_service(name)
    wrapper = ws.exe_from_config(state.binary_path)
    kept = [env[ENV_DATA_DIR]] if env.get(ENV_DATA_DIR) else []
    if wrapper is not None:
        kept.append(str(wrapper.parent.parent))
    secrets = env.get(ENV_SECRETS_FILE)
    left = bool(secrets) and Path(secrets).exists()
    return ServiceUninstallResult(
        service=name, removed=True, secrets_file=secrets if left else None, kept=kept,
        delete_secrets=f'Remove-Item "{secrets}"   (in an administrator PowerShell)' if left else None,
        front_door_removed=front_removed,
    )


def status(*, workspace: str | None = None) -> ServiceStatusResult:
    require_windows()
    name = ls.service_name(workspace)
    state = service_state(name)
    path, env, logpath = _config(name, state.binary_path) if state.installed else (None, {}, None)
    return ServiceStatusResult(
        service=name,
        manager="winsw",
        installed=state.installed,
        running=state.state == "RUNNING",
        state=state.state,
        detail=f"exit code {state.exit_code}" if state.exit_code else "",
        at_boot="AUTO_START" in state.start_type if state.installed else None,
        boot_detail=state.start_type or "unknown",
        main_pid=state.pid,
        active_since_iso=None,
        user=state.account,
        restarts=None,
        definition_path=str(path) if path else None,
        secrets_file=env.get(ENV_SECRETS_FILE) if env.get(ENV_SECRETS_FILE) and Path(env[ENV_SECRETS_FILE]).exists() else None,
        install_command=command_line("install"),
        logs=logpath or "",
    )


def _control(action: str, workspace: str | None) -> ServiceControlResult:
    require_windows()
    name = ls.service_name(workspace)
    if not is_admin():
        raise NeedsAdminError(
            f"{'Starting' if action == 'start' else 'Stopping'} the HiroLeague service",
            command_line(action, *_options(workspace)),
        )
    if not service_state(name).installed:
        raise ServiceError(f"The service {name} is not installed. Install it with: {command_line('install')}")
    state = start_service(name) if action == "start" else stop_service(name)
    return ServiceControlResult(
        service=name, action="started" if action == "start" else "stopped", state=state.state, main_pid=state.pid,
    )


def start(*, workspace: str | None = None) -> ServiceControlResult:
    return _control("start", workspace)


def stop(*, workspace: str | None = None) -> ServiceControlResult:
    return _control("stop", workspace)
