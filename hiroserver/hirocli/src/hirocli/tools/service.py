"""Linux service tools: install, remove and inspect the Hiro server as a systemd service.

CLI-only (``hiro service ...``): installing a system service needs root, so neither the agent nor
the HTTP surface (both run inside the unprivileged server) can do it. The Hiro-specific unit is
built by ``hirocli.linux_service``; the system work is ``hiro_commons.systemd_service``.
"""

from __future__ import annotations

from dataclasses import dataclass

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
    uninstall_service,
    unit_file_name,
    unit_path,
)

from .. import linux_service as ls
from .base import Tool, ToolParam

log = Logger.get("TOOLS.SERVICE")


@dataclass
class ServiceInstallResult:
    service: str  # unit file name, e.g. "hiro.service"
    user: str
    unit_path: str
    env_file: str
    env_file_created: bool  # False: an existing secrets file was kept as it was
    exec_start: str
    started: bool


@dataclass
class ServiceUninstallResult:
    service: str
    removed: bool  # False: it was not installed
    env_file: str | None  # secrets file left in place, if any


@dataclass
class ServiceStatusResult:
    service: str
    installed: bool
    active_state: str
    sub_state: str
    enabled_state: str
    main_pid: int | None
    active_since_iso: str | None
    user: str
    restarts: int | None
    unit_path: str | None
    env_file: str | None
    hiro_executable: str | None


class ServiceInstallTool(Tool):
    surfaces = frozenset({"cli"})
    name = "service_install"
    description = (
        "Linux: install the Hiro server as a systemd service that starts at boot and restarts "
        "on failure (needs root)"
    )
    params = {
        "user": ToolParam(
            str,
            "User the service runs as (default: the user running the install)",
            required=False,
        ),
        "workspace": ToolParam(
            str,
            "Workspace the service runs (default: the service user's default workspace)",
            required=False,
        ),
    }

    def execute(self, user: str | None = None, workspace: str | None = None) -> ServiceInstallResult:
        require_linux()
        exe = ls.hiro_executable()
        user_name = user or default_service_user()
        if not is_root():
            raise NeedsRootError(
                "Installing the HiroLeague service",
                ls.sudo_command(exe, "install", user=user_name, workspace=workspace),
            )
        service_user = resolve_service_user(user_name)
        spec = ls.build_spec(exe=exe, user=service_user.name, group=service_user.group, workspace=workspace)
        # Fail before writing anything when the service user can't even start `hiro`.
        check_user_can_run(service_user, [exe, "--help"])
        env_created = install_service(
            spec, service_user, ls.env_file_content(spec.name, service_user.name), start=True,
        )
        return ServiceInstallResult(
            service=unit_file_name(spec.name),
            user=service_user.name,
            unit_path=str(unit_path(spec.name)),
            env_file=str(spec.env_file),
            env_file_created=env_created,
            exec_start=" ".join(spec.exec_args),
            started=True,
        )


class ServiceUninstallTool(Tool):
    surfaces = frozenset({"cli"})
    name = "service_uninstall"
    description = "Linux: stop and remove the Hiro systemd service (needs root; keeps data and secrets)"
    params = {
        "workspace": ToolParam(str, "Workspace whose service to remove (default: the default service)", required=False),
    }

    def execute(self, workspace: str | None = None) -> ServiceUninstallResult:
        require_linux()
        name = ls.service_name(workspace)
        if not is_root():
            raise NeedsRootError(
                "Removing the HiroLeague service",
                ls.sudo_command(ls.hiro_executable(), "uninstall", user=None, workspace=workspace),
            )
        removed = uninstall_service(name)
        env_file = env_file_path(name)
        return ServiceUninstallResult(
            service=unit_file_name(name),
            removed=removed,
            env_file=str(env_file) if env_file.exists() else None,
        )


class ServiceStatusTool(Tool):
    surfaces = frozenset({"cli"})
    name = "service_status"
    description = "Linux: show the state of the Hiro systemd service"
    params = {
        "workspace": ToolParam(str, "Workspace whose service to show (default: the default service)", required=False),
    }

    def execute(self, workspace: str | None = None) -> ServiceStatusResult:
        require_linux()
        name = ls.service_name(workspace)
        state = service_state(name)
        try:
            exe: str | None = ls.hiro_executable()
        except Exception:
            # Only used to print the exact install command; status itself doesn't need it.
            log.debug("hiro executable not found for the status hint — HiroServer · service", exc_info=True)
            exe = None
        return ServiceStatusResult(
            service=unit_file_name(name),
            installed=state.installed,
            active_state=state.active_state,
            sub_state=state.sub_state,
            enabled_state=state.enabled_state,
            main_pid=state.main_pid,
            active_since_iso=state.active_since.isoformat() if state.active_since else None,
            user=state.user,
            restarts=state.restarts,
            unit_path=str(state.unit_path) if state.unit_path else None,
            env_file=str(state.env_file) if state.env_file else None,
            hiro_executable=exe,
        )
