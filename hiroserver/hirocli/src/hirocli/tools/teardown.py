"""Taking workspaces down: what `hiro uninstall`, `hiro workspaces teardown` and `hiro workspaces remove` do to each
(issue 430). Planned first, so the person reads exactly what will happen to which workspace before anything does.

For each workspace: its OS service first (a service would start the server again), only when that service runs *this*
registry's workspace (a Windows service keeps its own workspaces, in its own data folder, so a same-named workspace
here is another one); then its server; then, with purge, its folder. A service that needs an administrator to go
stops the rest for that workspace: its server and folder stay, since the service still runs them, and the words say
what to run. `uninstall` also takes the standalone gateways (`hirogate`) down.
"""

from __future__ import annotations

import getpass
import os
from dataclasses import dataclass, field
from pathlib import Path

from hiro_commons.log import Logger
from hiro_commons.process import read_running_pid
from hiro_commons.systemd_service import NeedsRootError, ServiceError
from hiro_commons.winsw_service import NeedsAdminError

from ..constants import PID_FILENAME
from ..domain.workspace import WorkspaceEntry, WorkspaceRegistry, load_registry, registry_path, remove_workspace
from . import server_control as ctrl

log = Logger.get("TOOLS.TEARDOWN")


@dataclass
class WorkspaceTeardown:
    id: str
    name: str
    path: str
    running: bool
    service: str | None  # the OS service that runs this workspace, removed first
    service_workspace: str | None  # what `hiro service uninstall --workspace` takes for it (None: the default service)
    purge: bool  # its folder is deleted
    leaves_list: bool  # its registry entry goes
    done: list[str] = field(default_factory=list)
    problem: str | None = None  # why the rest was left (a service only an administrator can remove)


@dataclass
class GatewayTeardown:
    name: str
    path: str
    running: bool
    purge: bool
    done: list[str] = field(default_factory=list)
    problem: str | None = None


@dataclass
class TeardownPlan:
    workspaces: list[WorkspaceTeardown] = field(default_factory=list)
    gateways: list[GatewayTeardown] = field(default_factory=list)

    def lines(self) -> list[str]:
        """What will happen, one line per workspace and gateway, in words."""
        out = [_workspace_line(w) for w in self.workspaces]
        out += [_gateway_line(g) for g in self.gateways]
        return out


def _workspace_line(w: WorkspaceTeardown) -> str:
    parts = []
    if w.service:
        parts.append(f"its service {w.service} is removed (needs an administrator)")
    parts.append("its server is stopped" if w.running else "its server isn't running")
    parts.append("its folder is deleted" if w.purge else "its folder is kept")
    if w.leaves_list:
        parts.append("it leaves the workspace list")
    return f"Workspace '{w.name}' ({w.path}): " + "; ".join(parts) + "."


def _gateway_line(g: GatewayTeardown) -> str:
    what = "stopped" if g.running else "not running"
    rest = "its files are deleted and it leaves the list" if g.purge else "its files are kept"
    return f"Gateway '{g.name}' ({g.path}): {what}; {rest}."


def _same_path(a: str | Path, b: str | Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _service_running(entry: WorkspaceEntry, is_default: bool) -> tuple[str, str | None] | None:
    """The installed OS service that runs this workspace: (its name, the --workspace it was installed with)."""
    from .service import system_module

    candidates = [entry.name] + ([None] if is_default else [])
    for asked in candidates:
        try:
            st = system_module().status(workspace=asked)
        except ServiceError as exc:  # no service manager here (or an unsupported system): no service to remove
            log.debug("No service status for the workspace", workspace=entry.name, error=str(exc))
            return None
        if not st.installed:
            continue
        own_registry = registry_path().parent
        if st.data_dir:  # Windows: the service's own data folder
            if _same_path(st.data_dir, own_registry):
                return st.service, asked
        elif st.user == getpass.getuser():  # Linux, Mac: the service account's own data folder is this one
            return st.service, asked
    return None


def plan_workspace(entry: WorkspaceEntry, registry: WorkspaceRegistry, *, purge: bool, leaves_list: bool) -> WorkspaceTeardown:
    service = _service_running(entry, registry.default_workspace == entry.id)
    return WorkspaceTeardown(
        id=entry.id,
        name=entry.name,
        path=entry.path,
        running=read_running_pid(Path(entry.path), PID_FILENAME) is not None,
        service=service[0] if service else None,
        service_workspace=service[1] if service else None,
        purge=purge,
        leaves_list=leaves_list or purge,
    )


def plan_uninstall(*, purge: bool) -> TeardownPlan:
    """Every workspace of this registry, and every standalone gateway."""
    registry = load_registry()
    plan = TeardownPlan(
        workspaces=[plan_workspace(e, registry, purge=purge, leaves_list=purge) for e in registry.workspaces.values()]
    )
    try:
        from hirogateway.service import get_status

        gateways = get_status().instances
    except Exception as exc:  # the gateway package or its registry unreadable: say so, take the workspaces down
        log.warning("⚠️ The standalone gateways couldn't be listed: they are left as they are", error=str(exc))
        gateways = []
    plan.gateways = [GatewayTeardown(name=g.name, path=g.path, running=g.running, purge=purge) for g in gateways]
    return plan


def carry_out_workspace(w: WorkspaceTeardown) -> None:
    from .service import ServiceUninstallTool

    if w.service:
        try:
            ServiceUninstallTool().execute(workspace=w.service_workspace)
            w.done.append(f"service {w.service} removed")
        except (NeedsAdminError, NeedsRootError) as exc:
            # The service still runs the server and its folder: both stay until it is gone.
            w.problem = f"its service {w.service} needs an administrator to remove: run {exc.command}, then again"
            return
        except ServiceError as exc:
            w.problem = f"its service {w.service} couldn't be removed ({exc}): its server and folder are kept"
            return
    was_running, _ = ctrl.stop_server(Path(w.path))
    if was_running:
        w.done.append("server stopped")
    if w.leaves_list:
        remove_workspace(w.id, purge=w.purge)
        w.done.append("folder deleted, left the list" if w.purge else "left the list")


def carry_out_gateway(g: GatewayTeardown) -> None:
    from hirogateway.instance import GatewayInstanceError
    from hirogateway.service import teardown_instance

    try:
        result = teardown_instance(g.name, purge=g.purge)
    except GatewayInstanceError as exc:
        g.problem = str(exc)
        return
    if result.stopped:
        g.done.append("stopped")
    if result.purged:
        g.done.append("files deleted")


def carry_out(plan: TeardownPlan) -> TeardownPlan:
    for w in plan.workspaces:
        carry_out_workspace(w)
    for g in plan.gateways:
        carry_out_gateway(g)
    return plan
