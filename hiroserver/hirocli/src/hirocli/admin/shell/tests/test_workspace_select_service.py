"""WorkspaceSelectService — mocked WorkspaceListTool (no NiceGUI)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from hirocli.admin.shell.workspace_service import WorkspaceSelectService


def test_workspace_select_service_load_options() -> None:
    mock_ws = MagicMock()
    mock_ws.workspaces = [{"id": "w1", "name": "One"}, {"id": "w2", "name": "Two"}]
    mock_ws.default_workspace = "w2"
    with patch("hirocli.admin.shell.workspace_service.WorkspaceListTool") as Tool:
        Tool.return_value.execute.return_value = mock_ws
        opts, default = WorkspaceSelectService.load_select_options(None)
    assert opts == {"w1": "One", "w2": "Two"}
    assert default == "w2"
