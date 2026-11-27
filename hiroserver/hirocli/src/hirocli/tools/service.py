"""Service tools: install, remove, start, stop and inspect the Hiro server as a system service.

The same five operations on each system, one module each: Linux runs it under systemd (``service_linux``), Windows
under WinSW (``service_windows``), Mac under launchd (``service_mac``). CLI-only (``hiro service ...``): installing a
system service needs root or an administrator, so neither the agent nor the HTTP surface (both run inside the
unprivileged server) can do it.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import ModuleType

from hiro_commons.constants.storage import CONFIG_FILENAME, REGISTRY_FILENAME
from hiro_commons.log import Logger
from hiro_commons.systemd_service import ServiceError

from ..domain.site_names import DEFAULT_CORE_NAME, check_core_name, domain_of
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


log = Logger.get("TOOLS.SERVICE")

_WORKSPACE_WAIT_S = 30.0


def service_data_dir(result: ServiceInstallResult) -> Path | None:
    """Where the service's own workspace registry lives: Windows names it (HIRO_DATA_DIR); Linux and Mac use the
    service account's own data folder."""
    if result.data_dir:
        return Path(result.data_dir)
    try:
        import pwd

        home = Path(pwd.getpwnam(result.user).pw_dir)
    except (ImportError, KeyError):
        return None
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "hiro"
    return home / ".local" / "share" / "hiro"


def _admin_of(data_dir: Path, workspace: str | None) -> tuple[int, str] | None:
    """The admin port and the core's LAN name of the service's workspace (by name or id, else its default), from its
    config.json."""
    try:
        reg = json.loads((data_dir / REGISTRY_FILENAME).read_text(encoding="utf-8"))
        entries = reg.get("workspaces") or {}
        key = workspace or reg.get("default_workspace")
        entry = entries.get(key) or next((e for e in entries.values() if e.get("name") == key), None)
        if entry is None:
            return None
        cfg = json.loads((Path(entry["path"]) / CONFIG_FILENAME).read_text(encoding="utf-8"))
        return int(cfg["admin_port"]), domain_of(cfg.get("core_name") or DEFAULT_CORE_NAME)
    except (OSError, ValueError, KeyError, TypeError):
        return None  # not made yet, or not readable from here: the caller waits, then says so


def wait_for_admin(result: ServiceInstallResult, workspace: str | None) -> tuple[int, str] | None:
    """Wait (up to half a minute) for the service's first start to make its workspace, and read where its admin is."""
    data_dir = service_data_dir(result)
    if data_dir is None or not result.started:
        return None
    deadline = time.monotonic() + _WORKSPACE_WAIT_S
    while True:
        admin = _admin_of(data_dir, workspace)
        if admin is not None or time.monotonic() > deadline:
            return admin
        time.sleep(0.5)


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


def install_and_find_admin(tool: ServiceInstallTool, workspace: str | None, **options: str | None) -> ServiceInstallResult:
    """`hiro service install`'s step: install, then say whether it was the first install and where the admin is. Run
    where the install runs (an elevated run on Windows): the service's data folder is its own and an
    administrator's."""
    system = system_module()
    try:
        was_there = system.status(workspace=workspace).installed
    except ServiceError as exc:  # the install below says what is wrong with this system
        log.debug("Could not tell whether the service was installed before", error=str(exc))
        was_there = False
    result = tool.execute(workspace=workspace, **options)
    result.first_install = not was_there
    admin = wait_for_admin(result, workspace)
    if admin is not None:
        result.admin_port, result.site_domain = admin
    else:
        log.warning("⚠️ The service's admin port couldn't be read: the install doesn't name it", service=result.service)
    return result


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
