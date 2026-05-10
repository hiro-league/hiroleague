from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from hiro_channel_sdk.models import ContentItem, MessageRouting, UnifiedMessage
from hirocli.domain.blob_store import DEFAULT_CHUNK_SIZE, blob_id_for_file, chunk_count_for_size
from hirocli.domain.conversation_channel import CHAT_CHANNEL_ID_METADATA_KEY, create_channel
from hirocli.domain.data_store import data_db_path, ensure_data_db
from hirocli.domain.message_attachments import list_attachments_for_message
from hirocli.domain.message_store import save_message
from hirocli.runtime.agent_manager import (
    AgentManager,
    _audio_extension_for_media_type,
    _normalize_reply_content,
    _reply_content_type,
)
from hirocli.services.tts.provider import TTSResult


def test_normalize_reply_content_keeps_plain_text() -> None:
    assert _normalize_reply_content("Hello") == "Hello"


def test_normalize_reply_content_extracts_provider_text_blocks() -> None:
    content = [
        {
            "type": "text",
            "text": "I'm sorry, I cannot help you with that.",
            "extras": {"signature": "opaque-provider-signature"},
        }
    ]

    assert _normalize_reply_content(content) == "I'm sorry, I cannot help you with that."


def test_normalize_reply_content_joins_multiple_text_blocks() -> None:
    content = [
        {"type": "text", "text": "First"},
        {"type": "non_text", "metadata": {"ignored": True}},
        {"type": "text", "text": "Second"},
    ]

    assert _normalize_reply_content(content) == "First\nSecond"


def test_reply_content_type_reports_block_count() -> None:
    assert _reply_content_type([{"type": "text", "text": "Hello"}]) == "list[1]"


def test_audio_extension_for_media_type() -> None:
    assert _audio_extension_for_media_type("audio/mpeg") == "mp3"
    assert _audio_extension_for_media_type("audio/mp3") == "mp3"
    assert _audio_extension_for_media_type("audio/wav") == "wav"
    assert _audio_extension_for_media_type("audio/mp4") == "m4a"


def test_resolve_thread_character_uses_chat_channel_metadata(tmp_path) -> None:
    ensure_data_db(tmp_path)
    import sqlite3

    with sqlite3.connect(str(data_db_path(tmp_path))) as conn:
        uid = int(conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()[0])
    channel = create_channel(tmp_path, name="selected", character_id="agent-a", user_id=uid)
    inbound = UnifiedMessage(
        routing=MessageRouting(
            id="user-msg-selected",
            channel="devices",
            direction="inbound",
            sender_id="u1",
            metadata={CHAT_CHANNEL_ID_METADATA_KEY: f"server-{channel.id}"},
        ),
        content=[ContentItem(content_type="text", body="hello")],
    )

    ctx = SimpleNamespace(workspace_path=tmp_path)
    mgr = AgentManager(ctx, SimpleNamespace(), tts_service=None)

    assert mgr._resolve_thread_character(inbound) == (
        str(channel.id),
        channel.id,
        "agent-a",
    )


@pytest.mark.asyncio
async def test_synthesize_and_send_stores_tts_attachment(tmp_path, monkeypatch) -> None:
    ensure_data_db(tmp_path)
    import sqlite3

    with sqlite3.connect(str(data_db_path(tmp_path))) as conn:
        uid = int(conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()[0])
    channel = create_channel(tmp_path, name="devices:u1", character_id="hiro", user_id=uid)

    inbound = UnifiedMessage(
        routing=MessageRouting(
            id="user-msg-1",
            channel="devices",
            direction="inbound",
            sender_id="u1",
        ),
        content=[ContentItem(content_type="text", body="hello")],
    )
    text_reply = UnifiedMessage(
        routing=MessageRouting(
            id="reply-msg-1",
            channel="devices",
            direction="outbound",
            sender_id="server",
            recipient_id="u1",
        ),
        content=[ContentItem(content_type="text", body="hi")],
    )
    reply_pk = await save_message(
        tmp_path,
        external_id=text_reply.routing.id,
        channel_id=channel.id,
        sender_type="agent",
        sender_id="server",
        content_type="text",
        body="hi",
    )

    class _FakeTts:
        async def synthesize(self, text, *, model=None, voice="", instructions="", **kwargs):
            assert text == "hi"
            assert model == "tts-model"
            assert voice == "voice-a"
            assert instructions == "speak clearly"
            return TTSResult(
                audio_bytes=b"tts bytes",
                mime_type="audio/mpeg",
                duration_ms=456,
                model="tts-model",
                voice="voice-a",
            )

    class _FakeComm:
        def __init__(self) -> None:
            self.outbound = []

        async def enqueue_outbound(self, msg) -> None:
            self.outbound.append(msg)

    def _resolve_character_voice(*args, **kwargs):
        return SimpleNamespace(model="tts-model", voice="voice-a", instructions="speak clearly")

    monkeypatch.setattr("hirocli.domain.preferences.load_preferences", lambda _wp: object())
    monkeypatch.setattr("hirocli.domain.preferences.resolve_character_voice", _resolve_character_voice)

    comm = _FakeComm()
    ctx = SimpleNamespace(
        workspace_path=tmp_path,
        device_names=SimpleNamespace(resolve=lambda device_id: device_id),
    )
    mgr = AgentManager(ctx, comm, tts_service=_FakeTts())

    await mgr._synthesize_and_send(
        inbound,
        text_reply,
        "hi",
        channel_id=channel.id,
        reply_message_pk=reply_pk,
        character_voice_models=["tts-model"],
    )

    assert len(comm.outbound) == 1
    voiced = comm.outbound[0]
    event = voiced.event
    assert event is not None
    # One conversation per user → voiced event broadcasts to every paired
    # device (no ``recipient_id`` so the gateway fans out to all of them).
    assert not voiced.routing.recipient_id, (
        "voiced event must broadcast to all devices in the user's conversation"
    )
    data = event.data
    assert base64.b64decode(data["audio"]) == b"tts bytes"
    assert data["mime_type"] == "audio/mpeg"
    assert data["duration_ms"] == 456
    assert data["ref"] == "message_attachment:reply-msg-1:0"
    assert data["chunk_size"] == DEFAULT_CHUNK_SIZE

    rows = list_attachments_for_message(tmp_path, reply_pk)
    assert len(rows) == 1
    row = rows[0]
    media_path = tmp_path / "data" / row["media_path"]
    assert media_path.read_bytes() == b"tts bytes"
    assert row["blob_id"] == blob_id_for_file(media_path)
    assert data["blob_id"] == row["blob_id"]
    assert data["size"] == row["size"] == len(b"tts bytes")
    assert data["chunk_count"] == chunk_count_for_size(row["size"], DEFAULT_CHUNK_SIZE)
    assert row["metadata"] == {
        "source": "character_tts",
        "reply_to_message_id": "user-msg-1",
        "model": "tts-model",
        "voice": "voice-a",
    }
    assert not (tmp_path / "tts_debug").exists()
