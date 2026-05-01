"""ChatChannelsService tests with mocked tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from hirocli.admin.features.chat_channels.service import ChatChannelsService


def test_list_no_workspace() -> None:
    r = ChatChannelsService().list_channels(None)
    assert not r.ok and r.error


def test_list_success() -> None:
    mock_out = MagicMock()
    mock_out.channels = [{"id": 1, "name": "General"}]
    with patch("hirocli.admin.features.chat_channels.service.ConversationChannelListTool") as T:
        T.return_value.execute.return_value = mock_out
        r = ChatChannelsService().list_channels("ws-1")
    assert r.ok and r.data == [{"id": 1, "name": "General"}]


def test_messages_all_uses_tool_flag() -> None:
    mock_out = MagicMock()
    mock_out.messages = [{"body": "x"}]
    with patch("hirocli.admin.features.chat_channels.service.MessageHistoryTool") as T:
        inst = T.return_value
        inst.execute.return_value = mock_out
        r = ChatChannelsService().list_messages_all("ws-1", 3)
    assert r.ok and r.data == [{"body": "x"}]
    inst.execute.assert_called_once_with(3, workspace="ws-1", all_messages=True)
