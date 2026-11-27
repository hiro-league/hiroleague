"""`hiro service` on Linux: the server as a systemd system service (``hiro_commons.systemd_service``)."""

from __future__ import annotations

import dataclasses

from hiro_commons.log import Logger
from hiro_commons.systemd_service import (
    NeedsRootError,
    check_user_can_run,
    default_service_user,
    env_file_path,
    install_service,
    is_root,
    require_linux,
    resolve_service_user,
    service_state,
    start_service,
    stop_service,
    uninstall_service,
    unit_file_name,
    unit_path,
)

from .. import front_door_setup as door
from .. import linux_service as ls
from ..constants import ENV_CORE_NAME
from ..domain.front_door import ENV_FRONT_DOOR
from .service_models import ServiceControlResult, ServiceInstallResult, ServiceStatusResult, ServiceUninstallResult

log = Logger.get("TOOLS.SERVICE")


def _logs(unit: str) -> str:
    return f"journalctl -u {unit} -f"


def install(*, user: str | None = None, workspace: str | None = None, core_name: str | None = None,
            **_: object) -> ServiceInstallResult:
    require_linux()
    exe = ls.hiro_executable()
    user_name = user or default_service_user()
    if not is_root():
        raise NeedsRootError(
            "Installing the HiroLeague service",
            ls.sudo_command(exe, "install", user=user_name, workspace=workspace, core_name=core_name),
        )
    service_user = resolve_service_user(user_name)
    spec = ls.build_spec(exe=exe, user=service_user.name, group=service_user.group, workspace=workspace)
    if core_name:
        spec = dataclasses.replace(spec, environment={**spec.environment, ENV_CORE_NAME: core_name})
    # Fail before writing anything when the service user can't even start `hiro`.
    check_user_can_run(service_user, [exe, "--help"])
    # The machine's front door, set up by the default service only (one per machine), before the core starts: the
    # core's account joins Caddy's group here, which a process started after it has.
    front = door.install_linux(service_user) if not workspace else None
    if front is not None:
        spec = dataclasses.replace(spec, environment={**spec.environment, ENV_FRONT_DOOR: front.admin})
    env_created = install_service(spec, service_user, ls.env_file_content(spec.name, service_user.name), start=True)
    unit = unit_file_name(spec.name)
    return ServiceInstallResult(
        service=unit,
        manager="systemd",
        user=service_user.name,
        definition_path=str(unit_path(spec.name)),
        secrets_file=str(spec.env_file),
        secrets_file_created=env_created,
        exec_start=" ".join(spec.exec_args),
        started=True,
        edit_secrets=f"sudoedit {spec.env_file}",
        restart_command=f"sudo systemctl restart {unit}",
        logs=_logs(unit),
        front_door=front.service if front else None,
        front_door_account=front.account if front else None,
        front_door_names=front.names if front else None,
    )


def uninstall(*, workspace: str | None = None) -> ServiceUninstallResult:
    require_linux()
    name = ls.service_name(workspace)
    if not is_root():
        raise NeedsRootError(
            "Removing the HiroLeague service",
            ls.sudo_command(ls.hiro_executable(), "uninstall", user=None, workspace=workspace),
        )
    removed = uninstall_service(name)
    front_removed = door.uninstall_linux() if not workspace else False
    env_file = env_file_path(name)
    left = env_file.exists()
    return ServiceUninstallResult(
        service=unit_file_name(name), removed=removed, secrets_file=str(env_file) if left else None,
        delete_secrets=f"sudo rm {env_file}" if left else None, front_door_removed=front_removed,
    )


def status(*, workspace: str | None = None) -> ServiceStatusResult:
    require_linux()
    name = ls.service_name(workspace)
    state = service_state(name)
    try:
        exe: str | None = ls.hiro_executable()
    except Exception:
        # Only used to print the exact install command; status itself doesn't need it.
        log.debug("hiro executable not found for the status hint — HiroServer · service", exc_info=True)
        exe = None
    unit = unit_file_name(name)
    return ServiceStatusResult(
        service=unit,
        manager="systemd",
        installed=state.installed,
        running=state.active_state == "active",
        state=state.active_state,
        detail=state.sub_state,
        at_boot=state.enabled_state == "enabled",
        boot_detail=state.enabled_state or "unknown",
        main_pid=state.main_pid,
        active_since_iso=state.active_since.isoformat() if state.active_since else None,
        user=state.user,
        restarts=state.restarts,
        definition_path=str(state.unit_path) if state.unit_path else None,
        secrets_file=str(state.env_file) if state.env_file else None,
        install_command=f"sudo {exe or 'hiro'} service install",
        logs=_logs(unit),
    )


def _control(action: str, workspace: str | None) -> ServiceControlResult:
    require_linux()
    name = ls.service_name(workspace)
    if not is_root():
        raise NeedsRootError(
            f"{'Starting' if action == 'start' else 'Stopping'} the HiroLeague service",
            ls.sudo_command(ls.hiro_executable(), action, user=None, workspace=workspace),
        )
    (start_service if action == "start" else stop_service)(name)
    state = service_state(name)
    return ServiceControlResult(
        service=unit_file_name(name),
        action="started" if action == "start" else "stopped",
        state=state.active_state,
        main_pid=state.main_pid,
    )


def start(*, workspace: str | None = None) -> ServiceControlResult:
    return _control("start", workspace)


def stop(*, workspace: str | None = None) -> ServiceControlResult:
    return _control("stop", workspace)
