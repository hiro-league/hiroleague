"""Service tools: install, remove, start, stop and inspect the Hiro server as a system service.

The same five operations on each system, one module each: Linux runs it under systemd (``service_linux``), Windows
under WinSW (``service_windows``), Mac under launchd (``service_mac``). CLI-only (``hiro service ...``): installing a
system service needs root or an administrator, so neither the agent nor the HTTP surface (both run inside the
unprivileged server) can do it.
"""

from __future__ import annotations

import sys
from types import ModuleType

from ..domain.site_names import check_core_name
from .base import Tool, ToolParam
from .service_models import ServiceControlResult, ServiceInstallResult, ServiceStatusResult, ServiceUninstallResult

_SYSTEMS = {"linux": "service_linux", "win32": "service_windows", "darwin": "service_mac"}


def current_system() -> str:
    return "linux" if sys.platform.startswith("linux") else sys.platform


def system_module() -> ModuleType:
    """This system's service operations (imported on first use: each pulls in its own system's helpers)."""
    import importlib

    name = _SYSTEMS.get(current_system())
    if name is None:
        from hiro_commons.systemd_service import ServiceError

        raise ServiceError(f"Running Hiro League as a service is not supported on {sys.platform}.")
    return importlib.import_module(f".{name}", __package__)


_WORKSPACE = ToolParam(str, "Workspace the service runs (default: the service's default workspace)", required=False)


class ServiceInstallTool(Tool):
    surfaces = frozenset({"cli"})
    name = "service_install"
    description = (
        "Install the Hiro server as a system service that starts at boot and restarts on failure "
        "(systemd, a Windows service or a Mac LaunchDaemon; needs root or an administrator)"
    )
    params = {
        "user": ToolParam(
            str, "Linux and Mac: the account the service runs as (default: the one installing it)", required=False,
        ),
        "workspace": _WORKSPACE,
        "home": ToolParam(
            str, "Windows: the folder for the program and its Python (default: %ProgramData%\\HiroLeague)",
            required=False,
        ),
        "data_dir": ToolParam(str, "Windows: the folder for the workspace (default: <home>\\data)", required=False),
        "source": ToolParam(
            str, "Windows: what to install for the service (default: this version of hiroleague)", required=False,
        ),
        "core_name": ToolParam(
            str, "The core's name, for the service's new workspace: its admin at <name>.local (default hiro); a "
                 "workspace that exists keeps its own", required=False,
        ),
    }

    def execute(
        self,
        user: str | None = None,
        workspace: str | None = None,
        home: str | None = None,
        data_dir: str | None = None,
        source: str | None = None,
        core_name: str | None = None,
    ) -> ServiceInstallResult:
        # Checked before anything is installed or an admin is asked: the service's first start sets its workspace up
        # with it (ENV_CORE_NAME)
        name = check_core_name(core_name) if core_name and core_name.strip() else None
        return system_module().install(user=user, workspace=workspace, home=home, data_dir=data_dir, source=source,
                                       core_name=name)


class ServiceUninstallTool(Tool):
    surfaces = frozenset({"cli"})
    name = "service_uninstall"
    description = "Stop and remove the Hiro service (needs root or an administrator; keeps data and secrets)"
    params = {"workspace": _WORKSPACE}

    def execute(self, workspace: str | None = None) -> ServiceUninstallResult:
        return system_module().uninstall(workspace=workspace)


class ServiceStatusTool(Tool):
    surfaces = frozenset({"cli"})
    name = "service_status"
    description = "Show the state of the Hiro service"
    params = {"workspace": _WORKSPACE}

    def execute(self, workspace: str | None = None) -> ServiceStatusResult:
        return system_module().status(workspace=workspace)


class ServiceStartTool(Tool):
    surfaces = frozenset({"cli"})
    name = "service_start"
    description = "Start the installed Hiro service (needs root or an administrator)"
    params = {"workspace": _WORKSPACE}

    def execute(self, workspace: str | None = None) -> ServiceControlResult:
        return system_module().start(workspace=workspace)


class ServiceStopTool(Tool):
    surfaces = frozenset({"cli"})
    name = "service_stop"
    description = "Stop the Hiro service until its next start or the next boot (needs root or an administrator)"
    params = {"workspace": _WORKSPACE}

    def execute(self, workspace: str | None = None) -> ServiceControlResult:
        return system_module().stop(workspace=workspace)
