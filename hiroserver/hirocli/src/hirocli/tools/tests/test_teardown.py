"""Taking workspaces down (issue 430): the plan says what happens to which workspace before anything does; a
workspace's own service goes first; another registry's same-named service is left alone; a service only an
administrator can remove leaves the workspace as it was; uninstall takes every workspace and makes none."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from hiro_commons.winsw_service import NeedsAdminError

from hirocli.constants import ENV_DATA_DIR
from hirocli.domain.workspace import create_workspace, load_registry
from hirocli.tools import service as service_tools
from hirocli.tools import server_control, teardown
from hirocli.tools.workspace import WorkspaceRemoveTool


class _Services:
    """The OS services, as `status` and `uninstall` see them: name → the data folder whose registry it runs."""

    def __init__(self, installed: dict[str, str], *, admin: bool = True) -> None:
        self.installed = installed
        self.admin = admin
        self.removed: list[str] = []

    @staticmethod
    def name(workspace: str | None) -> str:
        return f"hiro-{workspace}" if workspace else "hiro"

    def status(self, *, workspace: str | None = None) -> SimpleNamespace:
        name = self.name(workspace)
        return SimpleNamespace(service=name, installed=name in self.installed, data_dir=self.installed.get(name),
                               user="someone")

    def uninstall(self, *, workspace: str | None = None) -> SimpleNamespace:
        if not self.admin:
            raise NeedsAdminError("Removing the HiroLeague service", f"hiro service uninstall --workspace {workspace}")
        self.removed.append(self.name(workspace))
        return SimpleNamespace(removed=True)


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path))
    stopped: list[Path] = []
    monkeypatch.setattr(server_control, "stop_server", lambda path: (stopped.append(path) or (False, None)))
    import hirogateway.service as gw

    monkeypatch.setattr(gw, "get_status", lambda: SimpleNamespace(instances=[]))
    return tmp_path


def _services(monkeypatch, services: _Services) -> _Services:
    monkeypatch.setattr(service_tools, "system_module", lambda: services)
    return services


def test_the_plan_names_each_workspace_and_what_happens_to_it(data_dir: Path, monkeypatch) -> None:
    create_workspace("home")
    create_workspace("work")
    _services(monkeypatch, _Services({"hiro-work": str(data_dir)}))
    lines = teardown.plan_uninstall(purge=True).lines()
    assert len(lines) == 2
    home = next(line for line in lines if "'home'" in line)
    work = next(line for line in lines if "'work'" in line)
    assert "its folder is deleted" in home and "service" not in home
    assert "its service hiro-work is removed (needs an administrator)" in work


def test_uninstall_removes_the_service_first_then_the_workspace(data_dir: Path, monkeypatch) -> None:
    entry, _ = create_workspace("work")
    services = _services(monkeypatch, _Services({"hiro-work": str(data_dir)}))
    plan = teardown.carry_out(teardown.plan_uninstall(purge=True))
    assert services.removed == ["hiro-work"]
    assert plan.workspaces[0].done[0] == "service hiro-work removed"
    assert not load_registry().workspaces and not Path(entry.path).exists()


def test_a_same_named_service_of_another_registry_is_left_alone(data_dir: Path, monkeypatch, tmp_path: Path) -> None:
    create_workspace("default")
    # This PC's `hiro` service runs its own workspace, in its own data folder (ProgramData), not this one.
    services = _services(monkeypatch, _Services({"hiro": str(tmp_path / "ProgramData" / "HiroLeague" / "data")}))
    plan = teardown.carry_out(teardown.plan_uninstall(purge=False))
    assert services.removed == [] and plan.workspaces[0].service is None


def test_a_service_needing_an_administrator_leaves_the_workspace_as_it_was(data_dir: Path, monkeypatch) -> None:
    entry, _ = create_workspace("work")
    _services(monkeypatch, _Services({"hiro-work": str(data_dir)}, admin=False))
    stopped: list[Path] = []
    monkeypatch.setattr(server_control, "stop_server", lambda path: (stopped.append(path) or (True, 1)))
    plan = teardown.carry_out(teardown.plan_uninstall(purge=True))
    w = plan.workspaces[0]
    assert "needs an administrator" in (w.problem or "") and "hiro service uninstall --workspace work" in w.problem
    assert stopped == [] and Path(entry.path).exists() and load_registry().workspaces  # the service still runs it


def test_uninstall_with_no_workspace_makes_none(data_dir: Path, monkeypatch) -> None:
    _services(monkeypatch, _Services({}))
    plan = teardown.carry_out(teardown.plan_uninstall(purge=False))
    assert plan.workspaces == [] and not load_registry().workspaces  # before: it made `default` to tear it down


def test_workspace_remove_takes_its_service_down_first(data_dir: Path, monkeypatch) -> None:
    create_workspace("home")
    entry, _ = create_workspace("work")
    services = _services(monkeypatch, _Services({"hiro-work": str(data_dir)}))
    result = WorkspaceRemoveTool().execute(workspace="work", purge=True)
    assert services.removed == ["hiro-work"] and result.teardown is not None
    assert entry.id not in load_registry().workspaces and not Path(entry.path).exists()
