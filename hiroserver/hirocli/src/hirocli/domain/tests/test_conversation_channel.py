"""Conversation channel CRUD and message listing (data.db)."""

from __future__ import annotations

import sqlite3

import pytest

from hirocli.domain.conversation_channel import (
    create_channel,
    delete_channel,
    update_channel,
)
from hirocli.domain.data_store import data_db_path, ensure_data_db
from hirocli.domain.message_store import _sync_list, _sync_save


def _insert_message(
    workspace_path,
    channel_id: int,
    *,
    external_id: str,
    body: str = "hi",
) -> None:
    _sync_save(
        workspace_path,
        external_id=external_id,
        channel_id=channel_id,
        user_id=None,
        sender_type="user",
        sender_id="u1",
        content_type="text",
        body=body,
        media_path=None,
        metadata=None,
        created_at=None,
    )


def test_update_channel_name(tmp_path) -> None:
    ensure_data_db(tmp_path)
    uid = _default_user_id(tmp_path)
    ch = create_channel(
        tmp_path,
        name="Alpha",
        character_id="agent-a",
        user_id=uid,
    )
    updated = update_channel(tmp_path, ch.id, name="Beta")
    assert updated.name == "Beta"
    assert updated.character_id == "agent-a"


def test_update_channel_duplicate_name_raises(tmp_path) -> None:
    ensure_data_db(tmp_path)
    uid = _default_user_id(tmp_path)
    create_channel(tmp_path, name="One", character_id="a", user_id=uid)
    second = create_channel(tmp_path, name="Two", character_id="a", user_id=uid)
    with pytest.raises(ValueError, match="already exists"):
        update_channel(tmp_path, second.id, name="One")


def test_delete_channel_removes_messages(tmp_path) -> None:
    ensure_data_db(tmp_path)
    uid = _default_user_id(tmp_path)
    ch = create_channel(tmp_path, name="Zap", character_id="a", user_id=uid)
    _insert_message(tmp_path, ch.id, external_id="ext-1")
    _insert_message(tmp_path, ch.id, external_id="ext-2")
    delete_channel(tmp_path, ch.id)
    with sqlite3.connect(str(data_db_path(tmp_path))) as conn:
        m = conn.execute("SELECT COUNT(*) FROM messages WHERE channel_id = ?", (ch.id,)).fetchone()
        c = conn.execute("SELECT COUNT(*) FROM channels WHERE id = ?", (ch.id,)).fetchone()
    assert m[0] == 0
    assert c[0] == 0


def test_sync_list_limit_none_returns_all(tmp_path) -> None:
    ensure_data_db(tmp_path)
    uid = _default_user_id(tmp_path)
    ch = create_channel(tmp_path, name="Many", character_id="a", user_id=uid)
    for i in range(60):
        _insert_message(tmp_path, ch.id, external_id=f"e{i}", body=str(i))
    limited = _sync_list(tmp_path, ch.id, limit=50)
    assert len(limited) == 50
    all_rows = _sync_list(tmp_path, ch.id, limit=None)
    assert len(all_rows) == 60


def _default_user_id(workspace_path) -> int:
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        row = conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
    assert row is not None
    return int(row[0])
