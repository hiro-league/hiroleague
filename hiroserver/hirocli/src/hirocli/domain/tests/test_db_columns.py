"""workspace.db's add-only columns (domain/db.py): a column another connection added meanwhile is no failure."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hirocli.domain import db


class _Stale:
    """A connection whose table read is from before another connection added the column: the race two threads
    opening the database at a core's first start after an upgrade run (the merge's check, Nov 28, 2026)."""

    def __init__(self, conn: sqlite3.Connection, before: list[tuple]) -> None:
        self.conn, self.before = conn, before

    def execute(self, sql: str, *args):
        return iter(self.before) if sql.startswith("PRAGMA table_info") else self.conn.execute(sql, *args)


def test_a_column_another_connection_added_meanwhile_is_left_as_it_is(tmp_path: Path, monkeypatch) -> None:
    conn = sqlite3.connect(tmp_path / "w.db")
    conn.execute("CREATE TABLE t (id INTEGER)")
    before = list(conn.execute("PRAGMA table_info(t)"))
    conn.execute("ALTER TABLE t ADD COLUMN approved TEXT")  # the other connection, first
    monkeypatch.setattr(db, "_EXPECTED_COLUMNS", [("t", "approved", "TEXT")])
    db._add_missing_columns(_Stale(conn, before))  # raised "duplicate column name: approved"
    assert {row[1] for row in conn.execute("PRAGMA table_info(t)")} == {"id", "approved"}


def test_any_other_failure_to_add_a_column_still_fails(tmp_path: Path, monkeypatch) -> None:
    conn = sqlite3.connect(tmp_path / "w.db")
    conn.execute("CREATE TABLE t (id INTEGER)")
    monkeypatch.setattr(db, "_EXPECTED_COLUMNS", [("t", "broken", "TEXT NOT NULL")])  # NOT NULL with no default
    conn.execute("INSERT INTO t VALUES (1)")
    with pytest.raises(sqlite3.OperationalError):
        db._add_missing_columns(conn)
