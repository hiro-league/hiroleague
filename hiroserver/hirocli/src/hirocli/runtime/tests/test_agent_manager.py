"""Smoke tests for the slim ``AgentManager`` and reusable helpers.

The TTS attachment behaviour previously tested against
``AgentManager._synthesize_and_send`` now lives inside
``GraphEventSubscriber`` and is exercised end-to-end by integration tests
once the graph runner is wired. Those will be added under
``tests/test_graph_event_subscriber.py`` as the design stabilises.
"""

from __future__ import annotations

from types import SimpleNamespace

from hiro_channel_sdk.models import ContentItem, MessageRouting, UnifiedMessage
from hirocli.domain.conversation_channel import CHAT_CHANNEL_ID_METADATA_KEY, create_channel
from hirocli.domain.data_store import data_db_path, ensure_data_db
from hirocli.runtime.agent_manager import (
    AgentManager,
    _audio_extension_for_media_type,
    _normalize_reply_content,
    _reply_content_type,
)


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
