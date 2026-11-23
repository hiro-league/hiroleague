"""The one extensions list: extension_records is made once, with every row of extensions and channel_plugins.

The apps keep their ids and keys (no app pairs again); each channel plugin gets an id and no key (it pairs at its first
start); the two old tables stay exactly as they were. The copy is one transaction: when a row can't be copied, nothing
is left and the next start tries again.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hirocli.domain import db
from hirocli.domain.channel_config import list_channel_configs, load_channel_config
from hirocli.domain.extensions import KIND_APP, KIND_CHANNEL, get_paired_extension, list_paired_extensions

_OLD = """
CREATE TABLE extensions (extension_id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', public_key TEXT NOT NULL,
    paired_at TEXT NOT NULL, last_seen TEXT, info TEXT NOT NULL DEFAULT '{}', uses_before TEXT NOT NULL DEFAULT '[]');
CREATE TABLE channel_plugins (name TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1,
    command TEXT NOT NULL DEFAULT '[]', config TEXT NOT NULL DEFAULT '{}', workspace_dir TEXT NOT NULL DEFAULT '');
INSERT INTO extensions VALUES ('e-home', 'home', 'KEY-HOME', '2026-11-01T10:00:00+00:00', NULL,
    '{"name": "home", "version": "1.2"}', '["old"]');
INSERT INTO extensions VALUES ('e-net', 'net', 'KEY-NET', '2026-11-02T10:00:00+00:00', '2026-11-20T10:00:00+00:00',
    '{"name": "net"}', '[]');
INSERT INTO channel_plugins VALUES ('whatsapp', 0, '["hiro-channel-whatsapp"]', '{"owner_number": "2010"}', '');
INSERT INTO channel_plugins VALUES ('devices', 1, '[]', '{}', 'C:/src');
"""


def _old_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    path = db.db_path(workspace)
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(_OLD)
    return workspace


def _dump(workspace: Path, table: str) -> list[tuple]:
    with sqlite3.connect(db.db_path(workspace)) as conn:
        return conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()


def test_the_first_start_copies_every_row_and_leaves_the_old_tables(tmp_path: Path, caplog) -> None:
    workspace = _old_workspace(tmp_path)
    before = (_dump(workspace, "extensions"), _dump(workspace, "channel_plugins"))
    caplog.set_level("INFO", logger=db.__name__)

    db.ensure_db(workspace)

    assert (_dump(workspace, "extensions"), _dump(workspace, "channel_plugins")) == before
    home = get_paired_extension(workspace, "e-home")
    assert home is not None
    assert (home.name, home.kind, home.public_key, home.relays_chat, home.started_by_core) == (
        "home", KIND_APP, "KEY-HOME", False, False)
    assert home.uses_before == ["old"] and home.info["version"] == "1.2"
    assert [e.extension_id for e in list_paired_extensions(workspace)] == ["e-home", "e-net"]
    channels = list_paired_extensions(workspace, kind=KIND_CHANNEL)
    assert sorted(c.name for c in channels) == ["devices", "whatsapp"]
    assert all(c.public_key == "" and c.relays_chat and c.started_by_core and len(c.extension_id) == 32 for c in channels)
    whatsapp = load_channel_config(workspace, "whatsapp")
    assert whatsapp is not None and (whatsapp.enabled, whatsapp.command, whatsapp.config) == (
        False, ["hiro-channel-whatsapp"], {"owner_number": "2010"})
    assert [c.name for c in list_channel_configs(workspace)] == ["devices", "whatsapp"]
    assert "2 app(s) and 2 channel plugin(s) copied, counts match" in caplog.text


def test_the_copy_runs_once(tmp_path: Path) -> None:
    workspace = _old_workspace(tmp_path)
    db.ensure_db(workspace)
    db._initialized.clear()  # a new process
    with sqlite3.connect(db.db_path(workspace)) as conn:
        conn.execute("INSERT INTO extensions VALUES ('e-late', 'late', 'K', '2026-11-03', NULL, '{}', '[]')")
    db.ensure_db(workspace)
    assert get_paired_extension(workspace, "e-late") is None  # read once, at the copy; unread after


def test_a_row_that_cant_be_copied_leaves_nothing(tmp_path: Path, monkeypatch) -> None:
    workspace = _old_workspace(tmp_path)
    before = (_dump(workspace, "extensions"), _dump(workspace, "channel_plugins"))
    # A table that refuses the channel rows: the copy fails half way
    monkeypatch.setattr(db, "_EXTENSION_RECORDS_DDL", db._EXTENSION_RECORDS_DDL.replace(
        "workspace_dir   TEXT NOT NULL DEFAULT ''", "workspace_dir   TEXT NOT NULL DEFAULT '', CHECK (kind = 'app')"))
    with pytest.raises(sqlite3.IntegrityError):
        db.ensure_db(workspace)
    with sqlite3.connect(db.db_path(workspace)) as conn:
        made = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'extension_records'").fetchone()
    assert made is None
    assert (_dump(workspace, "extensions"), _dump(workspace, "channel_plugins")) == before


def test_a_fresh_workspace_gets_an_empty_list(tmp_path: Path) -> None:
    workspace = tmp_path / "fresh"
    db.ensure_db(workspace)
    assert list_paired_extensions(workspace, kind=None) == []
