"""ChatChannelsService tests with mocked tools."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from hirocli.admin.features.chat_channels.service import ChatChannelsService


def test_list_no_workspace() -> None:
    r = ChatChannelsService().list_channels(None)
    assert not r.ok and r.error


def test_list_success() -> None:
    mock_out = MagicMock()
    mock_out.channels = [{"id": 1, "name": "General"}]
    with (
        patch("hirocli.admin.features.chat_channels.service.ConversationChannelListTool") as T,
        patch("hirocli.admin.features.chat_channels.service.min_channel_id", return_value=1),
        patch(
            "hirocli.admin.features.chat_channels.service.read_channel_thumbnail_bytes",
            return_value=None,
        ),
        patch.object(ChatChannelsService, "_workspace_path", lambda self, _ws: Path(".")),
    ):
        T.return_value.execute.return_value = mock_out
        r = ChatChannelsService().list_channels("ws-1")
    assert r.ok
    assert r.data == [
        {
            "id": 1,
            "name": "General",
            "is_lowest_id_channel": True,
            "photo_data_url": None,
        }
    ]


def test_messages_all_uses_sync_history_for_admin_ui() -> None:
    with (
        patch.object(ChatChannelsService, "_workspace_path", lambda self, _ws: Path(".")),
        patch("hirocli.admin.features.chat_channels.service._sync_history") as hist,
    ):
        hist.return_value = [
            {"id": "ext-1", "message_pk": 7, "content": [], "channel_id": 3},
        ]
        r = ChatChannelsService().list_messages_all("ws-1", 3)
    assert r.ok and r.data == [
        {"id": "ext-1", "message_pk": 7, "content": [], "channel_id": 3},
    ]
    hist.assert_called_once_with(Path("."), 3, limit=None)
