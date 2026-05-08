"""Message audio attachments are tracked separately from message rows."""

from __future__ import annotations

import base64
import sqlite3

import pytest

from hiro_channel_sdk.constants import CONTENT_TYPE_AUDIO
from hiro_channel_sdk.models import ContentItem, MessageRouting, UnifiedMessage
from hirocli.domain.blob_store import (
    DEFAULT_CHUNK_SIZE,
    blob_id_for_file,
    chunk_count_for_size,
)
from hirocli.domain.conversation_channel import (
    DEFAULT_CONVERSATION_CHANNEL_NAME,
    _get_channel_by_name,
    create_channel,
)
from hirocli.domain.data_store import data_db_path, ensure_data_db
from hirocli.domain.files_resolver import resolve_blob_id, resolve_ref
from hirocli.domain.message_attachments import attachment_ref, list_attachments_for_message
from hirocli.domain.message_store import persist_inbound, save_message
from hirocli.tools.conversation import MessageHistoryTool


def _default_user_id(workspace_path) -> int:
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        row = conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
    assert row is not None
    return int(row[0])


def _default_channel_id(workspace_path, user_id: int) -> int:
    """Return the seeded user-scoped ``General`` channel id."""
    channel = _get_channel_by_name(
        workspace_path,
        DEFAULT_CONVERSATION_CHANNEL_NAME,
        user_id=user_id,
    )
    assert channel is not None, "default General channel should be seeded"
    return channel.id


def test_messages_schema_no_longer_has_media_path(tmp_path) -> None:
    ensure_data_db(tmp_path)
    with sqlite3.connect(str(data_db_path(tmp_path))) as conn:
        message_cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
        attachment_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(message_attachments)")
        }

    assert "media_path" not in message_cols
    assert {
        "message_pk",
        "slot_index",
        "content_type",
        "blob_id",
        "media_type",
        "size",
        "media_path",
        "duration_ms",
        "metadata",
    }.issubset(attachment_cols)


@pytest.mark.asyncio
async def test_persist_inbound_audio_creates_attachment_row(tmp_path) -> None:
    ensure_data_db(tmp_path)
    _default_user_id(tmp_path)  # seeds the workspace owner + General channel

    raw_audio = b"fake m4a bytes"
    msg = UnifiedMessage(
        routing=MessageRouting(
            id="msg-audio-1",
            channel="devices",
            direction="inbound",
            sender_id="u1",
        ),
        content=[
            ContentItem(
                content_type=CONTENT_TYPE_AUDIO,
                body=base64.b64encode(raw_audio).decode("ascii"),
                metadata={
                    "mime_type": "audio/m4a",
                    "duration_ms": 1234,
                    "description": "hello transcript",
                },
            ),
        ],
    )

    message_pk = await persist_inbound(tmp_path, msg)
    rows = list_attachments_for_message(tmp_path, message_pk)

    assert len(rows) == 1
    row = rows[0]
    media_path = tmp_path / "data" / row["media_path"]
    assert media_path.read_bytes() == raw_audio
    assert row["slot_index"] == 0
    assert row["content_type"] == CONTENT_TYPE_AUDIO
    assert row["media_type"] == "audio/m4a"
    assert row["size"] == len(raw_audio)
    assert row["duration_ms"] == 1234
    assert row["blob_id"] == blob_id_for_file(media_path)
    assert row["metadata"] == {
        "source": "user_audio",
        "transcript": "hello transcript",
    }

    with sqlite3.connect(str(data_db_path(tmp_path))) as conn:
        body = conn.execute(
            "SELECT body FROM messages WHERE id = ?",
            (message_pk,),
        ).fetchone()[0]
    assert body == "hello transcript"


@pytest.mark.asyncio
async def test_message_history_returns_audio_metadata_without_bytes(tmp_path) -> None:
    ensure_data_db(tmp_path)
    uid = _default_user_id(tmp_path)
    # Single per-user conversation: persist_inbound writes to the seeded ``General`` channel.
    channel_id = _default_channel_id(tmp_path, uid)

    raw_audio = b"history audio bytes"
    msg = UnifiedMessage(
        routing=MessageRouting(
            id="msg-history-audio",
            channel="devices",
            direction="inbound",
            sender_id="u1",
        ),
        content=[
            ContentItem(
                content_type=CONTENT_TYPE_AUDIO,
                body=base64.b64encode(raw_audio).decode("ascii"),
                metadata={
                    "mime_type": "audio/m4a",
                    "duration_ms": 900,
                    "description": "history transcript",
                },
            ),
        ],
    )

    await persist_inbound(tmp_path, msg)
    result = MessageHistoryTool().execute(channel_id, workspace_path=tmp_path)

    assert len(result.messages) == 1
    history_message = result.messages[0]
    assert history_message["id"] == "msg-history-audio"
    assert "external_id" not in history_message
    assert "media_path" not in history_message
    assert history_message["content"][0] == {
        "content_type": "text",
        "body": "history transcript",
    }

    audio = history_message["content"][1]
    metadata = audio["metadata"]
    assert audio["content_type"] == CONTENT_TYPE_AUDIO
    assert audio["body"] == attachment_ref("msg-history-audio", 0)
    assert "audio" not in metadata
    assert metadata["source"] == "user_audio"
    assert metadata["transcript"] == "history transcript"
    assert metadata["media_type"] == "audio/m4a"
    assert metadata["size"] == len(raw_audio)
    assert metadata["chunk_size"] == DEFAULT_CHUNK_SIZE
    assert metadata["chunk_count"] == chunk_count_for_size(len(raw_audio), DEFAULT_CHUNK_SIZE)
    assert metadata["duration_ms"] == 900
    assert metadata["blob_id"].startswith("sha256:")


@pytest.mark.asyncio
async def test_message_attachment_ref_and_blob_id_resolve_to_saved_audio(tmp_path) -> None:
    ensure_data_db(tmp_path)
    _default_user_id(tmp_path)  # seeds the workspace owner + General channel

    raw_audio = b"resolver audio bytes"
    msg = UnifiedMessage(
        routing=MessageRouting(
            id="msg:resolver:audio",
            channel="devices",
            direction="inbound",
            sender_id="u1",
        ),
        content=[
            ContentItem(
                content_type=CONTENT_TYPE_AUDIO,
                body=base64.b64encode(raw_audio).decode("ascii"),
                metadata={"mime_type": "audio/m4a"},
            ),
        ],
    )

    message_pk = await persist_inbound(tmp_path, msg)
    attachment = list_attachments_for_message(tmp_path, message_pk)[0]
    ref = attachment_ref("msg:resolver:audio", 0)

    ref_path, ref_media_type, ref_blob_id = resolve_ref(tmp_path, ref)
    blob_path, blob_media_type = resolve_blob_id(tmp_path, attachment["blob_id"])

    assert ref_path.read_bytes() == raw_audio
    assert ref_media_type == "audio/m4a"
    assert ref_blob_id == attachment["blob_id"]
    assert blob_path == ref_path
    assert blob_media_type == "audio/m4a"


@pytest.mark.asyncio
async def test_message_history_after_filters_by_created_at(tmp_path) -> None:
    ensure_data_db(tmp_path)
    uid = _default_user_id(tmp_path)
    channel = create_channel(tmp_path, name="after-filter", character_id="hiro", user_id=uid)
    await save_message(
        tmp_path,
        external_id="old-msg",
        channel_id=channel.id,
        user_id=uid,
        sender_type="user",
        sender_id="u1",
        content_type="text",
        body="old",
        created_at="2026-05-08T10:00:00Z",
    )
    await save_message(
        tmp_path,
        external_id="new-msg",
        channel_id=channel.id,
        user_id=uid,
        sender_type="agent",
        sender_id="server",
        content_type="text",
        body="new",
        created_at="2026-05-08T10:00:01Z",
    )

    result = MessageHistoryTool().execute(
        channel.id,
        after="2026-05-08T10:00:00Z",
        workspace_path=tmp_path,
    )

    assert [message["id"] for message in result.messages] == ["new-msg"]


@pytest.mark.asyncio
async def test_persist_inbound_routes_all_devices_into_one_user_channel(tmp_path) -> None:
    """Regression: two devices = two ``sender_id`` values, but ONE shared channel.

    Guards against the historical drift where channels were keyed by
    ``f"{routing.channel}:{routing.sender_id}"``, which gave each device its
    own conversation thread. The end-state contract is WhatsApp-style:
    one user, one conversation, regardless of which device sent the message.
    """
    ensure_data_db(tmp_path)
    uid = _default_user_id(tmp_path)
    expected_channel_id = _default_channel_id(tmp_path, uid)

    msg_a = UnifiedMessage(
        routing=MessageRouting(
            id="msg-from-device-a",
            channel="devices",
            direction="inbound",
            sender_id="device-a-uuid",
        ),
        content=[ContentItem(content_type="text", body="hi from A")],
    )
    msg_b = UnifiedMessage(
        routing=MessageRouting(
            id="msg-from-device-b",
            channel="devices",
            direction="inbound",
            sender_id="device-b-uuid",
        ),
        content=[ContentItem(content_type="text", body="hi from B")],
    )

    await persist_inbound(tmp_path, msg_a)
    await persist_inbound(tmp_path, msg_b)

    with sqlite3.connect(str(data_db_path(tmp_path))) as conn:
        rows = conn.execute(
            "SELECT external_id, channel_id FROM messages WHERE external_id IN (?, ?)",
            ("msg-from-device-a", "msg-from-device-b"),
        ).fetchall()
        channel_count = conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]

    assert {row[1] for row in rows} == {expected_channel_id}, (
        "both devices must write into the same per-user channel"
    )
    # Only the seeded ``General`` channel should exist — no per-device channels.
    assert channel_count == 1
