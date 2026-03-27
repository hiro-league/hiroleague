"""WorkspaceService unit tests — mocked tools and process helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hirocli.admin.features.workspaces.service import WorkspaceService
from hirocli.domain.workspace import WorkspaceError
from hirocli.tools.server_models import SetupResult, StartResult


def test_list_rows_enriches_running_and_current() -> None:
    mock_ws = MagicMock()
    mock_ws.workspaces = [
        {"id": "w1", "name": "One", "path": "/p1"},
        {"id": "w2", "name": "Two", "path": "/p2"},
    ]
    with (
        patch("hirocli.admin.features.workspaces.service.WorkspaceListTool") as W,
        patch("hirocli.admin.features.workspaces.service.read_pid") as rp,
        patch("hirocli.admin.features.workspaces.service.is_running") as ir,
    ):
        W.return_value.execute.return_value = mock_ws
        rp.side_effect = [100, None]
        ir.side_effect = [True, False]
        r = WorkspaceService().list_rows(hosting_workspace_id="w2")
    assert r.ok and r.data is not None
    assert len(r.data) == 2
    assert r.data[0]["running"] is True and r.data[0]["pid"] == 100
    assert r.data[0]["is_current"] is False
    assert r.data[1]["is_current"] is True


def test_list_rows_failure() -> None:
    with patch("hirocli.admin.features.workspaces.service.WorkspaceListTool") as W:
        W.return_value.execute.side_effect = RuntimeError("no registry")
        r = WorkspaceService().list_rows(None)
    assert not r.ok


def test_create_empty_name() -> None:
    r = WorkspaceService().create("   ", None)
    assert not r.ok


def test_create_success() -> None:
    with patch("hirocli.admin.features.workspaces.service.WorkspaceCreateTool") as T:
        T.return_value.execute.return_value = MagicMock()
        r = WorkspaceService().create("lab", None)
    assert r.ok and r.data and "lab" in r.data


def test_stop_blocked_for_hosting() -> None:
    r = WorkspaceService().stop("same", "same")
    assert not r.ok and "Cannot stop" in (r.error or "")


def test_remove_blocked_for_hosting() -> None:
    r = WorkspaceService().remove("x", purge=False, hosting_workspace_id="x")
    assert not r.ok and "Cannot remove" in (r.error or "")


def test_update_nothing_selected() -> None:
    r = WorkspaceService().update(
        "w1",
        name=None,
        gateway_url=None,
        set_default=False,
        previous_display_name="n",
    )
    assert not r.ok


def test_start_success_tuple() -> None:
    sr = StartResult(
        workspace="w",
        workspace_path="/p",
        already_running=False,
        pid=42,
        http_host="127.0.0.1",
        http_port=8080,
        admin_port=8083,
    )
    with patch("hirocli.admin.features.workspaces.service.StartTool") as T:
        T.return_value.execute.return_value = sr
        r = WorkspaceService().start("w1")
    assert r.ok and r.data == ("w", False, 42)


def test_setup_requires_gateway() -> None:
    r = WorkspaceService().setup(
        "w1",
        gateway_url="  ",
        http_port=None,
        skip_autostart=False,
        start_server=False,
        elevated_task=False,
    )
    assert not r.ok


def test_setup_success_returns_setup_result() -> None:
    setup = SetupResult(
        workspace="w",
        workspace_path="/p",
        device_id="d",
        gateway_url="ws://x",
        http_port=1,
        master_key="/k",
        desktop_pub="pubb64",
        autostart_registered=True,
        autostart_method="skipped",
        server_started=False,
        providers_imported=0,
    )
    with patch("hirocli.admin.features.workspaces.service.SetupTool") as T:
        T.return_value.execute.return_value = setup
        r = WorkspaceService().setup(
            "w1",
            gateway_url="ws://h:1",
            http_port=None,
            skip_autostart=True,
            start_server=False,
            elevated_task=False,
        )
    assert r.ok and r.data is setup


def test_get_public_key_workspace_error() -> None:
    with patch("hirocli.admin.features.workspaces.service.WorkspaceGetPublicKeyTool") as T:
        T.return_value.execute.side_effect = WorkspaceError("not configured")
        r = WorkspaceService().get_public_key("w1")
    assert not r.ok


@pytest.mark.parametrize("system", ["Windows", "Darwin", "Linux"])
def test_open_folder_success(system: str) -> None:
    with (
        patch("platform.system", return_value=system),
        patch("subprocess.Popen") as P,
    ):
        r = WorkspaceService().open_folder("/tmp/ws")
    assert r.ok
    assert P.call_count == 1


def test_open_folder_empty_path() -> None:
    r = WorkspaceService().open_folder("")
    assert not r.ok
