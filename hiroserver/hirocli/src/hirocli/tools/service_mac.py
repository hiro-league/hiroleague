"""`hiro service` on a Mac: the server as a LaunchDaemon (``hiro_commons.launchd_service``)."""

from __future__ import annotations

import dataclasses
import os
import plistlib

from hiro_commons.launchd_service import (
    install_service,
    plist_path,
    require_mac,
    service_state,
    start_service,
    stop_service,
    uninstall_service,
)
from hiro_commons.log import Logger
from hiro_commons.systemd_service import NeedsRootError, default_service_user, resolve_service_user, write_env_file

from .. import front_door_setup as door
from .. import linux_service as ls
from .. import mac_service as ms
from ..domain.front_door import ENV_FRONT_DOOR
from .service_models import ServiceControlResult, ServiceInstallResult, ServiceStatusResult, ServiceUninstallResult

log = Logger.get("TOOLS.SERVICE")

_WHY_ROOT = (
    f"It writes the service to /Library/LaunchDaemons and its secrets file to {ms.HOME.as_posix()}, "
    "and asks launchd to load it."
)


def _is_root() -> bool:
    return os.geteuid() == 0


def _needs_root(action: str, verb: str, *, user: str | None, workspace: str | None) -> NeedsRootError:
    return NeedsRootError(
        f"{verb} the HiroLeague service",
        ms.sudo_command(ls.hiro_executable(), action, user=user, workspace=workspace),
        why=_WHY_ROOT,
    )


def install(*, user: str | None = None, workspace: str | None = None, **_: object) -> ServiceInstallResult:
    require_mac()
    exe = ls.hiro_executable()
    user_name = user or default_service_user()
    if not _is_root():
        raise _needs_root("install", "Installing", user=user_name, workspace=workspace)
    service_user = resolve_service_user(user_name)
    # Fail before writing anything when the service's account can't even start `hiro`.
    ms.check_user_can_run(service_user, exe)
    ms.prepare_home(service_user, workspace)
    name = ls.service_name(workspace)
    secrets = ms.secrets_file(workspace)
    created = write_env_file(secrets, ms.env_file_content(name, service_user.name, workspace), service_user)
    spec = ms.build_spec(exe=exe, user=service_user, workspace=workspace)
    # The machine's front door, set up by the default service only (one per machine).
    front = door.install_mac(service_user, ms.HOME) if not workspace else None
    if front is not None:
        spec = dataclasses.replace(spec, environment={**spec.environment, ENV_FRONT_DOOR: front.admin})
    path = install_service(spec)
    return ServiceInstallResult(
        service=spec.label,
        manager="launchd",
        user=service_user.name,
        definition_path=path.as_posix(),
        secrets_file=secrets.as_posix(),
        secrets_file_created=created,
        exec_start=" ".join(spec.program_args),
        started=True,
        edit_secrets=f"sudo nano '{secrets.as_posix()}'",
        restart_command=f"sudo launchctl kickstart -k system/{spec.label}",
        logs=f"{ms.log_file(workspace).as_posix()} (before the server's own log opens), then the workspace's logs",
        front_door=front.service if front else None,
        front_door_account=front.account if front else None,
    )


def uninstall(*, workspace: str | None = None) -> ServiceUninstallResult:
    require_mac()
    if not _is_root():
        raise _needs_root("uninstall", "Removing", user=None, workspace=workspace)
    label = ms.label(workspace)
    removed = uninstall_service(label)
    front_removed = door.uninstall_mac() if not workspace else False
    secrets = ms.secrets_file(workspace)
    left = secrets.exists()
    return ServiceUninstallResult(
        service=label, removed=removed, secrets_file=secrets.as_posix() if left else None,
        delete_secrets=f"sudo rm '{secrets.as_posix()}'" if left else None, front_door_removed=front_removed,
    )


def _plist_user(label: str) -> str:
    try:
        with plist_path(label).open("rb") as fh:
            return str(plistlib.load(fh).get("UserName", ""))
    except (OSError, plistlib.InvalidFileException):
        log.debug("The LaunchDaemon's plist can't be read for its user — HiroServer · service", exc_info=True)
        return ""


def status(*, workspace: str | None = None) -> ServiceStatusResult:
    require_mac()
    label = ms.label(workspace)
    state = service_state(label)
    secrets = ms.secrets_file(workspace)
    try:
        exe = ls.hiro_executable()
    except Exception:
        # Only used to print the exact install command; status itself doesn't need it.
        log.debug("hiro executable not found for the status hint — HiroServer · service", exc_info=True)
        exe = "hiro"
    return ServiceStatusResult(
        service=label,
        manager="launchd",
        installed=state.installed,
        running=state.state == "running",
        state=state.state,
        detail=f"last exit code {state.last_exit_code}" if state.last_exit_code else "",
        at_boot=True if state.installed else None,  # RunAtLoad: a loaded LaunchDaemon starts at every boot
        boot_detail="RunAtLoad",
        main_pid=state.pid,
        active_since_iso=None,
        user=_plist_user(label) if state.installed else "",
        restarts=(state.runs - 1) if state.runs else None,
        definition_path=state.plist_path.as_posix() if state.plist_path else None,
        secrets_file=secrets.as_posix() if secrets.exists() else None,
        install_command=f"sudo {exe} service install",
        logs=ms.log_file(workspace).as_posix(),
    )


def _control(action: str, workspace: str | None) -> ServiceControlResult:
    require_mac()
    if not _is_root():
        raise _needs_root(action, "Starting" if action == "start" else "Stopping", user=None, workspace=workspace)
    label = ms.label(workspace)
    (start_service if action == "start" else stop_service)(label)
    state = service_state(label)
    return ServiceControlResult(
        service=label, action="started" if action == "start" else "stopped", state=state.state, main_pid=state.pid,
    )


def start(*, workspace: str | None = None) -> ServiceControlResult:
    return _control("start", workspace)


def stop(*, workspace: str | None = None) -> ServiceControlResult:
    return _control("stop", workspace)
