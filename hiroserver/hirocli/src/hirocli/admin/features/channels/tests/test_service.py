"""ChannelService — mocked tools, no NiceGUI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from hirocli.admin.features.channels.service import ChannelService


def test_list_channels_no_workspace() -> None:
    r = ChannelService().list_channels(None)
    assert not r.ok and r.error


def test_list_channels_success() -> None:
    mock_ch = MagicMock()
    mock_ch.channels = [{"name": "devices", "enabled": True}]
    with patch("hirocli.admin.features.channels.service.ChannelListTool") as T:
        T.return_value.execute.return_value = mock_ch
        r = ChannelService().list_channels("ws-1")
    assert r.ok and r.data == [{"name": "devices", "enabled": True}]


def test_list_channels_tool_error() -> None:
    with patch("hirocli.admin.features.channels.service.ChannelListTool") as T:
        T.return_value.execute.side_effect = RuntimeError("disk")
        r = ChannelService().list_channels("ws-1")
    assert not r.ok and "disk" in (r.error or "")


def test_enable_success() -> None:
    with patch("hirocli.admin.features.channels.service.ChannelEnableTool") as T:
        T.return_value.execute.return_value = MagicMock()
        r = ChannelService().enable_channel("telegram", "ws-1")
    assert r.ok and r.data and "telegram" in r.data


def test_enable_tool_error() -> None:
    with patch("hirocli.admin.features.channels.service.ChannelEnableTool") as T:
        T.return_value.execute.side_effect = RuntimeError("config locked")
        r = ChannelService().enable_channel("telegram", "ws-1")
    assert not r.ok and "locked" in (r.error or "")


def test_disable_mandatory_propagates_tool_error() -> None:
    with patch("hirocli.admin.features.channels.service.ChannelDisableTool") as T:
        T.return_value.execute.side_effect = ValueError(
            "The 'devices' channel is mandatory and cannot be disabled."
        )
        r = ChannelService().disable_channel("devices", "ws-1")
    assert not r.ok and "mandatory" in (r.error or "").lower()


def test_disable_success() -> None:
    with patch("hirocli.admin.features.channels.service.ChannelDisableTool") as T:
        T.return_value.execute.return_value = MagicMock()
        r = ChannelService().disable_channel("telegram", "ws-1")
    assert r.ok


def test_disable_tool_value_error() -> None:
    with patch("hirocli.admin.features.channels.service.ChannelDisableTool") as T:
        T.return_value.execute.side_effect = ValueError("not configured")
        r = ChannelService().disable_channel("telegram", "ws-1")
    assert not r.ok and "not configured" in (r.error or "")
