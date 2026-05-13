"""ChatChannelsService tests with mocked tools."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hirocli.admin.features.chat_channels.service import (
    ChatChannelsService,
    _sync_history_by_pks,
)
from hirocli.domain.conversation_channel import create_channel
from hirocli.domain.data_store import ensure_data_db
from hirocli.domain.message_store import save_message


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
    hist.assert_called_once_with(Path("."), 3, after=None, after_id=None, limit=None)


def test_messages_tail_uses_sync_history_cursor() -> None:
    with (
        patch.object(ChatChannelsService, "_workspace_path", lambda self, _ws: Path(".")),
        patch("hirocli.admin.features.chat_channels.service._sync_history") as hist,
    ):
        hist.return_value = []
        r = ChatChannelsService().list_messages_all(
            "ws-1",
            3,
            after="2026-05-11T10:00:00Z",
            after_id="ext-1",
            limit=50,
        )
    assert r.ok and r.data == []
    hist.assert_called_once_with(
        Path("."),
        3,
        after="2026-05-11T10:00:00Z",
        after_id="ext-1",
        limit=50,
    )


def test_messages_by_pk_uses_scoped_hydrator() -> None:
    with (
        patch.object(ChatChannelsService, "_workspace_path", lambda self, _ws: Path(".")),
        patch("hirocli.admin.features.chat_channels.service._sync_history_by_pks") as by_pks,
    ):
        by_pks.return_value = [
            {"id": "ext-2", "message_pk": 8, "content": [], "channel_id": 3},
        ]
        r = ChatChannelsService().list_messages_all("ws-1", 3, message_pks=[8])
    assert r.ok and r.data == [
        {"id": "ext-2", "message_pk": 8, "content": [], "channel_id": 3},
    ]
    by_pks.assert_called_once_with(Path("."), 3, [8])


@pytest.mark.asyncio
async def test_messages_by_pk_hydrator_parses_agent_metadata(tmp_path: Path) -> None:
    ensure_data_db(tmp_path)
    channel = create_channel(tmp_path, name="Cost test", character_id="hiro", user_id=1)
    message_pk = await save_message(
        tmp_path,
        external_id="reply-with-cost",
        channel_id=channel.id,
        sender_type="agent",
        sender_id="server",
        content_type="text",
        body="hi",
        metadata={
            "agent": {
                "status": "completed",
                "usage_total": {"output_tokens": 6},
                "cost": {
                    "currency": "USD",
                    "estimated_total": 0.00003675,
                    "pricing_available": True,
                },
            }
        },
    )

    rows = _sync_history_by_pks(tmp_path, channel.id, [message_pk])

    assert rows == [
        {
            "id": "reply-with-cost",
            "message_pk": message_pk,
            "channel_id": channel.id,
            "sender_type": "agent",
            "sender_id": "server",
            "created_at": rows[0]["created_at"],
            "content": [{"content_type": "text", "body": "hi"}],
            "metadata": {
                "agent": {
                    "status": "completed",
                    "usage_total": {"output_tokens": 6},
                    "cost": {
                        "currency": "USD",
                        "estimated_total": 0.00003675,
                        "pricing_available": True,
                    },
                }
            },
        }
    ]
