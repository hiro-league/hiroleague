"""DeviceService — mocked tools, no NiceGUI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from hirocli.admin.features.devices.service import DeviceService


def test_list_devices_no_workspace() -> None:
    r = DeviceService().list_devices(None)
    assert not r.ok


def test_list_devices_tool_error() -> None:
    with patch("hirocli.admin.features.devices.service.DeviceListTool") as T:
        T.return_value.execute.side_effect = RuntimeError("registry")
        r = DeviceService().list_devices("ws-1")
    assert not r.ok


def test_list_devices_success() -> None:
    mock_d = MagicMock()
    mock_d.devices = [{"device_id": "d1", "device_name": "Phone"}]
    with patch("hirocli.admin.features.devices.service.DeviceListTool") as T:
        T.return_value.execute.return_value = mock_d
        r = DeviceService().list_devices("ws-1")
    assert r.ok and r.data and r.data[0]["device_id"] == "d1"


def test_generate_pairing_tool_error() -> None:
    with patch("hirocli.admin.features.devices.service.DeviceAddTool") as T:
        T.return_value.execute.side_effect = RuntimeError("pairing failed")
        r = DeviceService().generate_pairing_code("ws-1")
    assert not r.ok


def test_generate_pairing_success() -> None:
    raw = MagicMock()
    raw.code = "123456"
    raw.expires_at = "2025-01-01T00:00:00Z"
    raw.gateway_url = "wss://x"
    raw.qr_payload = '{"code":"123456"}'
    with patch("hirocli.admin.features.devices.service.DeviceAddTool") as T:
        T.return_value.execute.return_value = raw
        r = DeviceService().generate_pairing_code("ws-1")
    assert r.ok and r.data is not None
    assert r.data.code == "123456"
    assert r.data.qr_payload == '{"code":"123456"}'


def test_revoke_tool_exception() -> None:
    with patch("hirocli.admin.features.devices.service.DeviceRevokeTool") as T:
        T.return_value.execute.side_effect = ValueError("bad id")
        r = DeviceService().revoke_device("x", "ws-1")
    assert not r.ok and "bad id" in (r.error or "")


def test_revoke_not_removed() -> None:
    mock_r = MagicMock()
    mock_r.removed = False
    mock_r.device_id = "x"
    with patch("hirocli.admin.features.devices.service.DeviceRevokeTool") as T:
        T.return_value.execute.return_value = mock_r
        r = DeviceService().revoke_device("x", "ws-1")
    assert not r.ok


def test_revoke_success() -> None:
    mock_r = MagicMock()
    mock_r.removed = True
    mock_r.device_id = "x"
    with patch("hirocli.admin.features.devices.service.DeviceRevokeTool") as T:
        T.return_value.execute.return_value = mock_r
        r = DeviceService().revoke_device("x", "ws-1")
    assert r.ok
