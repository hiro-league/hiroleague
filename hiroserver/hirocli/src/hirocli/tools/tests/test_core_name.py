"""The core's own name (Installing apps, phase 5): picked when a workspace is set up, kept afterwards.

`hiro workspaces setup --name` (or its question) names a new workspace's core; a service installed with a name makes
its workspace with it at its first start (HIRO_CORE_NAME). A workspace keeps the name it was set up with: another
name asked for it is refused in words, and a re-run of setup keeps it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.constants import ENV_CORE_NAME, ENV_DATA_DIR
from hirocli.domain.config import Config, load_config
from hirocli.domain.workspace import WorkspaceError, resolve_workspace
from hirocli.tools import server
from hirocli.tools.server import SetupTool, StartTool, core_name_for


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A registry and workspaces of this test's own."""
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path))
    monkeypatch.delenv(ENV_CORE_NAME, raising=False)
    return tmp_path


def _setup(**kw: object) -> object:
    return SetupTool().execute(gateway_url="ws://localhost:8765", skip_env_import=True, **kw)


def _config() -> Config:
    entry, _ = resolve_workspace(None)
    return load_config(Path(entry.path))


def test_the_name_asked_is_a_new_workspaces_and_the_workspace_keeps_its_own() -> None:
    hiro = Config()
    assert core_name_for(hiro, is_new=True, asked=None) == "hiro"
    assert core_name_for(hiro, is_new=True, asked=" TestPC ") == "testpc"
    assert core_name_for(Config(core_name="testpc"), is_new=False, asked=None) == "testpc"
    assert core_name_for(Config(core_name="testpc"), is_new=False, asked="testpc") == "testpc"
    with pytest.raises(WorkspaceError, match="named hiro"):
        core_name_for(hiro, is_new=False, asked="testpc")  # Simone's workspace stays hiro
    with pytest.raises(WorkspaceError, match="one word"):
        core_name_for(hiro, is_new=True, asked="test pc")


def test_setup_names_a_new_workspace_and_a_re_run_keeps_the_name(data_dir: Path) -> None:
    result = _setup(core_name="testpc")
    assert result.core_name == "testpc"
    assert (_config().core_name, _config().site_domain()) == ("testpc", "testpc.local")

    assert _setup().core_name == "testpc"  # set up again without a name: kept
    with pytest.raises(WorkspaceError):
        _setup(core_name="other")
    assert _config().core_name == "testpc"


def test_a_workspace_set_up_without_a_name_is_hiro(data_dir: Path) -> None:
    assert _setup().core_name == "hiro"
    assert _config().site_domain() == "hiro.local"


def _start_without_a_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server.ctrl, "start_server", lambda *a, **kw: None)
    monkeypatch.setattr(server, "read_pid", lambda *a, **kw: None)


def test_a_services_first_start_makes_its_workspace_with_the_name_it_was_given(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _start_without_a_server(monkeypatch)
    monkeypatch.setenv(ENV_CORE_NAME, "testpc")
    assert StartTool().execute().provisioned is True
    assert _config().core_name == "testpc"


def test_a_service_given_another_name_keeps_the_workspaces_own_and_says_so(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _setup()  # an existing workspace, named hiro
    _start_without_a_server(monkeypatch)
    monkeypatch.setenv(ENV_CORE_NAME, "testpc")
    assert StartTool().execute().provisioned is False
    assert _config().core_name == "hiro"
    assert any("keeps its own" in r.getMessage() and r.levelname == "WARNING" for r in caplog.records)
