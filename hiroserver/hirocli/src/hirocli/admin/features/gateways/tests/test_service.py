"""GatewayService — mocked tools, no NiceGUI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from hirogateway.service import GatewayInstanceStatusEntry

from hirocli.admin.features.gateways.service import GatewayService


def test_list_instances_success() -> None:
    inst = GatewayInstanceStatusEntry(
        name="main",
        is_default=True,
        running=True,
        pid=42,
        host="0.0.0.0",
        port=8765,
        path="/gw/main",
    )
    mock_r = MagicMock()
    mock_r.instances = [inst]
    with patch("hirocli.admin.features.gateways.service.GatewayStatusTool") as T:
        T.return_value.execute.return_value = mock_r
        r = GatewayService().list_instances()
    assert r.ok and r.data is not None
    assert r.data[0]["name"] == "main"
    assert r.data[0]["running"] is True
    assert r.data[0]["pid"] == 42


def test_list_instances_tool_error() -> None:
    with patch("hirocli.admin.features.gateways.service.GatewayStatusTool") as T:
        T.return_value.execute.side_effect = RuntimeError("registry")
        r = GatewayService().list_instances()
    assert not r.ok


def test_start_success() -> None:
    sr = MagicMock()
    sr.already_running = False
    sr.pid = 99
    with patch("hirocli.admin.features.gateways.service.GatewayStartTool") as T:
        T.return_value.execute.return_value = sr
        r = GatewayService().start("gw1")
    assert r.ok and r.data == (False, 99)


def test_start_empty_name() -> None:
    r = GatewayService().start("")
    assert not r.ok


def test_stop_tool_error() -> None:
    with patch("hirocli.admin.features.gateways.service.GatewayStopTool") as T:
        T.return_value.execute.side_effect = RuntimeError("not running")
        r = GatewayService().stop("gw1")
    assert not r.ok


def test_stop_success() -> None:
    sr = MagicMock()
    sr.was_running = True
    with patch("hirocli.admin.features.gateways.service.GatewayStopTool") as T:
        T.return_value.execute.return_value = sr
        r = GatewayService().stop("gw1")
    assert r.ok and r.data is True


def test_setup_validation() -> None:
    r = GatewayService().setup_instance(name="   ", desktop_public_key="k", port=1)
    assert not r.ok


def test_setup_instance_tool_error() -> None:
    with patch("hirocli.admin.features.gateways.service.GatewaySetupTool") as T:
        T.return_value.execute.side_effect = RuntimeError("disk full")
        r = GatewayService().setup_instance(
            name="g1",
            desktop_public_key="abc",
            port=8765,
        )
    assert not r.ok


def test_setup_success_message() -> None:
    out = MagicMock()
    out.instance_name = "g1"
    out.port = 8765
    out.autostart_registered = True
    out.autostart_method = "registry"
    with patch("hirocli.admin.features.gateways.service.GatewaySetupTool") as T:
        T.return_value.execute.return_value = out
        r = GatewayService().setup_instance(
            name="g1",
            desktop_public_key="abc",
            port=8765,
        )
    assert r.ok and r.data and "g1" in r.data and "8765" in r.data


def test_teardown_instance_tool_error() -> None:
    with patch("hirocli.admin.features.gateways.service.GatewayTeardownTool") as T:
        T.return_value.execute.side_effect = RuntimeError("in use")
        r = GatewayService().teardown_instance("g1", purge=False)
    assert not r.ok


def test_teardown_success_message() -> None:
    out = MagicMock()
    out.instance_name = "g1"
    out.stopped = True
    out.autostart_removed = True
    out.purged = False
    with patch("hirocli.admin.features.gateways.service.GatewayTeardownTool") as T:
        T.return_value.execute.return_value = out
        r = GatewayService().teardown_instance("g1", purge=False)
    assert r.ok and r.data and "removed" in r.data.lower()
