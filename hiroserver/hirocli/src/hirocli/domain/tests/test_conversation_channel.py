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
from hirocli.domain.message_attachments import insert_attachment
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
    assert ch.id != 1, "fixture expects seeded General keeps id 1"
    _insert_message(tmp_path, ch.id, external_id="ext-1")
    _insert_message(tmp_path, ch.id, external_id="ext-2")
    first_message_pk = _sync_list(tmp_path, ch.id, limit=1)[0]["id"]
    insert_attachment(
        tmp_path,
        message_pk=first_message_pk,
        slot_index=0,
        content_type="audio",
        blob_id="sha256:" + ("a" * 64),
        media_type="audio/m4a",
        size=10,
        media_path="media/fake.m4a",
    )
    delete_channel(tmp_path, ch.id)
    with sqlite3.connect(str(data_db_path(tmp_path))) as conn:
        m = conn.execute("SELECT COUNT(*) FROM messages WHERE channel_id = ?", (ch.id,)).fetchone()
        a = conn.execute("SELECT COUNT(*) FROM message_attachments").fetchone()
        c = conn.execute("SELECT COUNT(*) FROM channels WHERE id = ?", (ch.id,)).fetchone()
    assert m[0] == 0
    assert a[0] == 0
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


def test_delete_primary_lowest_channel_id_raises(tmp_path) -> None:
    ensure_data_db(tmp_path)
    with pytest.raises(ValueError, match="primary"):
        delete_channel(tmp_path, 1)


def test_create_channel_records_description(tmp_path) -> None:
    ensure_data_db(tmp_path)
    uid = _default_user_id(tmp_path)
    ch = create_channel(
        tmp_path,
        name="Desk",
        character_id="agent-a",
        user_id=uid,
        description=" Team status ",
    )
    assert ch.description == "Team status"


def _default_user_id(workspace_path) -> int:
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        row = conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
    assert row is not None
    return int(row[0])
