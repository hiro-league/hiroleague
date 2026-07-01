"""Per-conversation memory-ingestion watermark (``memory_ingest_cursors`` in data.db)."""

from __future__ import annotations

from hirocli.domain.conversation_channel import (
    clear_channel_messages,
    create_channel,
    delete_channel,
)
from hirocli.domain.data_store import ensure_data_db
from hirocli.domain.memory_ingest_cursor import advance_cursor, get_cursor


def test_cursor_absent_then_upserts_per_channel(tmp_path) -> None:
    ensure_data_db(tmp_path)
    ch = create_channel(tmp_path, name="Alpha", character_id="agent-a")

    # A fresh conversation has no watermark → controller would read history from the start.
    assert get_cursor(tmp_path, ch.id) is None

    # First advance creates the row.
    advance_cursor(
        tmp_path, ch.id, last_ingested_id="msg-3", last_ingested_at="2026-07-01T09:00:00+00:00"
    )
    assert get_cursor(tmp_path, ch.id) == {
        "last_ingested_id": "msg-3",
        "last_ingested_at": "2026-07-01T09:00:00+00:00",
    }

    # Second advance upserts in place (one row per channel; watermark moves forward).
    advance_cursor(
        tmp_path, ch.id, last_ingested_id="msg-7", last_ingested_at="2026-07-01T09:10:00+00:00"
    )
    cur = get_cursor(tmp_path, ch.id)
    assert cur is not None and cur["last_ingested_id"] == "msg-7"

    # Cursors are per-conversation — a different channel starts empty.
    ch2 = create_channel(tmp_path, name="Beta", character_id="agent-b")
    assert get_cursor(tmp_path, ch2.id) is None


def test_delete_channel_removes_cursor(tmp_path) -> None:
    ensure_data_db(tmp_path)
    create_channel(tmp_path, name="Primary", character_id="agent-a")  # lowest id — undeletable
    ch = create_channel(tmp_path, name="Beta", character_id="agent-b")
    advance_cursor(
        tmp_path, ch.id, last_ingested_id="m1", last_ingested_at="2026-07-01T09:00:00+00:00"
    )
    assert get_cursor(tmp_path, ch.id) is not None

    delete_channel(tmp_path, ch.id)
    # No orphan cursor left behind (the FK cascade isn't enforced, so it's deleted explicitly).
    assert get_cursor(tmp_path, ch.id) is None


def test_clear_channel_messages_resets_cursor(tmp_path) -> None:
    ensure_data_db(tmp_path)
    ch = create_channel(tmp_path, name="C", character_id="agent-a")
    advance_cursor(
        tmp_path, ch.id, last_ingested_id="m1", last_ingested_at="2026-07-01T09:00:00+00:00"
    )
    assert get_cursor(tmp_path, ch.id) is not None

    clear_channel_messages(tmp_path, ch.id)
    # Cleared conversation → watermark reset so the next turn starts fresh (start-from-now).
    assert get_cursor(tmp_path, ch.id) is None
