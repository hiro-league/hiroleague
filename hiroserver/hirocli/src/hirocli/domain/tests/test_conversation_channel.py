"""Conversation channel CRUD and message listing (data.db)."""

from __future__ import annotations

import sqlite3

import pytest

from hirocli.domain.conversation_channel import (
    clear_channel_messages,
    create_channel,
    delete_channel,
    update_channel,
    _get_channel_by_id,
)
from hirocli.domain.data_store import data_db_path, ensure_data_db
from hirocli.domain.message_attachments import insert_attachment, media_file_path
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


def test_clear_channel_messages_removes_messages_keeps_channel(tmp_path) -> None:
    ensure_data_db(tmp_path)
    uid = _default_user_id(tmp_path)
    ch = create_channel(tmp_path, name="WipeMsg", character_id="a", user_id=uid)
    assert ch.last_deleted == 0
    _insert_message(tmp_path, ch.id, external_id="ext-clear-1")
    _insert_message(tmp_path, ch.id, external_id="ext-clear-2")
    epoch = clear_channel_messages(tmp_path, ch.id)
    assert epoch == 1
    reloaded = _get_channel_by_id(tmp_path, ch.id)
    assert reloaded is not None
    assert reloaded.last_deleted == 1
    assert reloaded.last_message_at is None
    with sqlite3.connect(str(data_db_path(tmp_path))) as conn:
        m = conn.execute("SELECT COUNT(*) FROM messages WHERE channel_id = ?", (ch.id,)).fetchone()
        c = conn.execute("SELECT COUNT(*) FROM channels WHERE id = ?", (ch.id,)).fetchone()
        a = conn.execute("SELECT COUNT(*) FROM message_attachments").fetchone()
    assert int(m[0]) == 0
    assert int(c[0]) == 1
    assert int(a[0]) == 0


def test_clear_channel_messages_unlinks_file_when_blob_exclusive(tmp_path) -> None:
    ensure_data_db(tmp_path)
    uid = _default_user_id(tmp_path)
    ch = create_channel(tmp_path, name="BlobOne", character_id="a", user_id=uid)
    _insert_message(tmp_path, ch.id, external_id="e-blob")
    pk = _sync_list(tmp_path, ch.id, limit=1)[0]["id"]
    rel = "media/bychannel/exclusive.m4a"
    blob = "sha256:" + ("b" * 64)
    insert_attachment(
        tmp_path,
        message_pk=pk,
        slot_index=0,
        content_type="audio",
        blob_id=blob,
        media_type="audio/m4a",
        size=4,
        media_path=rel,
    )
    abs_mp = media_file_path(tmp_path, rel)
    abs_mp.parent.mkdir(parents=True, exist_ok=True)
    abs_mp.write_bytes(b"wxyz")
    clear_channel_messages(tmp_path, ch.id)
    assert not abs_mp.exists()


def test_clear_channel_messages_wipes_agent_checkpoint(tmp_path) -> None:
    """Bulk-clear must also drop the channel's LangGraph thread so the agent
    forgets the conversation. Thread id matches ``str(channel.id)`` per
    ``agent_manager._resolve_thread_character``."""
    from langgraph.checkpoint.base import empty_checkpoint
    from langgraph.checkpoint.sqlite import SqliteSaver

    from hirocli.domain.db import db_path

    ensure_data_db(tmp_path)
    uid = _default_user_id(tmp_path)
    ch1 = create_channel(tmp_path, name="A", character_id="a", user_id=uid)
    ch2 = create_channel(tmp_path, name="B", character_id="a", user_id=uid)
    workspace_db = str(db_path(tmp_path))
    with SqliteSaver.from_conn_string(workspace_db) as saver:
        for cid in (ch1.id, ch2.id):
            saver.put(
                {"configurable": {"thread_id": str(cid), "checkpoint_ns": ""}},
                empty_checkpoint(),
                {"source": "input"},
                {},
            )
        assert len(list(saver.list({"configurable": {"thread_id": str(ch1.id)}}))) == 1
        assert len(list(saver.list({"configurable": {"thread_id": str(ch2.id)}}))) == 1
    _insert_message(tmp_path, ch1.id, external_id="ext-cp-1")
    clear_channel_messages(tmp_path, ch1.id)
    with SqliteSaver.from_conn_string(workspace_db) as saver:
        assert list(saver.list({"configurable": {"thread_id": str(ch1.id)}})) == []
        # Other channels' threads must not be touched.
        assert len(list(saver.list({"configurable": {"thread_id": str(ch2.id)}}))) == 1


def test_clear_channel_messages_unlinks_only_target_channel_files(
    tmp_path,
) -> None:
    """Each attachment owns its own file. Clearing channel A unlinks A's files
    only; channel B's files (even with the same blob_id) remain untouched
    because they are stored under their own ``media_path``."""
    ensure_data_db(tmp_path)
    uid = _default_user_id(tmp_path)
    ch1 = create_channel(tmp_path, name="A", character_id="a", user_id=uid)
    ch2 = create_channel(tmp_path, name="B", character_id="a", user_id=uid)
    _insert_message(tmp_path, ch1.id, external_id="m1")
    _insert_message(tmp_path, ch2.id, external_id="m2")
    pk1 = _sync_list(tmp_path, ch1.id, limit=1)[0]["id"]
    pk2 = _sync_list(tmp_path, ch2.id, limit=1)[0]["id"]
    blob = "sha256:" + ("c" * 64)
    rel1 = "media/ch1/other1.m4a"
    rel2 = "media/ch2/other2.m4a"
    insert_attachment(
        tmp_path,
        message_pk=pk1,
        slot_index=0,
        content_type="audio",
        blob_id=blob,
        media_type="audio/m4a",
        size=1,
        media_path=rel1,
    )
    insert_attachment(
        tmp_path,
        message_pk=pk2,
        slot_index=0,
        content_type="audio",
        blob_id=blob,
        media_type="audio/m4a",
        size=1,
        media_path=rel2,
    )
    p1 = media_file_path(tmp_path, rel1)
    p2 = media_file_path(tmp_path, rel2)
    p1.parent.mkdir(parents=True, exist_ok=True)
    p2.parent.mkdir(parents=True, exist_ok=True)
    p1.write_bytes(b"a")
    p2.write_bytes(b"b")
    clear_channel_messages(tmp_path, ch1.id)
    assert not p1.exists()
    assert p2.exists()


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
