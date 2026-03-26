"""DashboardService — mock tools, no NiceGUI."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from hirocli.admin.features.dashboard.service import DashboardService
from hirogateway.service import GatewayInstanceStatusEntry, GatewayStatusResult


@dataclass
class _FakeStatusWs:
    server_running: bool


def test_get_overview_fails_when_workspace_list_raises() -> None:
    with patch("hirocli.admin.features.dashboard.service.WorkspaceListTool") as W:
        W.return_value.execute.side_effect = RuntimeError("registry locked")
        r = DashboardService().get_overview()
    assert not r.ok
    assert r.data is None
    assert r.error is not None
    assert "Unable to load workspaces" in r.error


def test_get_overview_aggregates_per_workspace_and_gateway() -> None:
    ws_mock = MagicMock()
    ws_mock.workspaces = [{"id": "a"}, {"id": "b"}]
    status_mock = MagicMock()
    status_mock.workspaces = [
        _FakeStatusWs(True),
        _FakeStatusWs(False),
    ]
    gw_mock = GatewayStatusResult(
        instances=[
            GatewayInstanceStatusEntry(
                name="g1",
                is_default=True,
                running=True,
                pid=1,
                host="0.0.0.0",
                port=8765,
                path="/p",
                desktop_connected=True,
                last_auth_error=None,
            )
        ]
    )
    dev_a = MagicMock()
    dev_a.devices = [1, 2]
    dev_b = MagicMock()
    dev_b.devices = [3]
    ch_a = MagicMock()
    ch_a.channels = [{"enabled": True}, {"enabled": False}]
    ch_b = MagicMock()
    ch_b.channels = [{"enabled": True}]

    with (
        patch("hirocli.admin.features.dashboard.service.WorkspaceListTool") as W,
        patch("hirocli.admin.features.dashboard.service.StatusTool") as S,
        patch("hirocli.admin.features.dashboard.service.GatewayStatusTool") as G,
        patch("hirocli.admin.features.dashboard.service.DeviceListTool") as D,
        patch("hirocli.admin.features.dashboard.service.ChannelListTool") as C,
    ):
        W.return_value.execute.return_value = ws_mock
        S.return_value.execute.return_value = status_mock
        G.return_value.execute.return_value = gw_mock
        D.return_value.execute.side_effect = [dev_a, dev_b]
        C.return_value.execute.side_effect = [ch_a, ch_b]
        r = DashboardService().get_overview()

    assert r.ok and r.data is not None
    d = r.data
    assert d.total_workspaces == 2
    assert d.running_workspaces == 1
    assert d.gateway_running is True
    assert d.gateway_desktop_connected is True
    assert d.gateway_auth_error is None
    assert d.total_devices == 3
    assert d.total_channels == 3
    assert d.enabled_channels == 2


def test_get_overview_swallows_status_gateway_device_channel_errors() -> None:
    ws_mock = MagicMock()
    ws_mock.workspaces = [{"id": "x"}]
    with (
        patch("hirocli.admin.features.dashboard.service.WorkspaceListTool") as W,
        patch("hirocli.admin.features.dashboard.service.StatusTool") as S,
        patch("hirocli.admin.features.dashboard.service.GatewayStatusTool") as G,
        patch("hirocli.admin.features.dashboard.service.DeviceListTool") as D,
        patch("hirocli.admin.features.dashboard.service.ChannelListTool") as C,
    ):
        W.return_value.execute.return_value = ws_mock
        S.return_value.execute.side_effect = RuntimeError("boom")
        G.return_value.execute.side_effect = RuntimeError("boom")
        D.return_value.execute.side_effect = RuntimeError("boom")
        C.return_value.execute.side_effect = RuntimeError("boom")
        r = DashboardService().get_overview()
    assert r.ok and r.data is not None
    d = r.data
    assert d.total_workspaces == 1
    assert d.running_workspaces == 0
    assert d.gateway_running is False
    assert d.total_devices == 0
    assert d.total_channels == 0
    assert d.enabled_channels == 0


def test_get_overview_gateway_auth_error_surface() -> None:
    ws_mock = MagicMock()
    ws_mock.workspaces = []
    gw_mock = GatewayStatusResult(
        instances=[
            GatewayInstanceStatusEntry(
                name="g1",
                is_default=True,
                running=True,
                pid=1,
                host="0.0.0.0",
                port=8765,
                path="/p",
                desktop_connected=False,
                last_auth_error="bad token",
            )
        ]
    )
    with (
        patch("hirocli.admin.features.dashboard.service.WorkspaceListTool") as W,
        patch("hirocli.admin.features.dashboard.service.StatusTool") as S,
        patch("hirocli.admin.features.dashboard.service.GatewayStatusTool") as G,
    ):
        W.return_value.execute.return_value = ws_mock
        S.return_value.execute.return_value = MagicMock(workspaces=[])
        G.return_value.execute.return_value = gw_mock
        r = DashboardService().get_overview()
    assert r.ok and r.data is not None
    assert r.data.gateway_auth_error == "bad token"
