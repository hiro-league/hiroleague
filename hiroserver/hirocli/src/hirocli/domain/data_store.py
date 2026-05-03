"""Data store module — manages data.db for user content.

Separate from workspace.db (system config). data.db holds users, channels,
and messages — data that should survive a workspace config reset.

Storage layout:
    <workspace>/data/data.db
    <workspace>/data/media/<channel_id>/<message_pk>.<ext>

Follows the same ensure/upgrade pattern as domain/db.py.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from hiro_commons.constants.storage import DATA_DB_FILENAME, DATA_DIR, MEDIA_DIR
from hiro_commons.log import Logger
from hiro_commons.timestamps import utc_iso, utc_now

log = Logger.get("DATA_STORE")

_initialized: set[str] = set()

_DEFAULT_USER_NAME = "owner"
_DEFAULT_CHANNEL_NAME = "General"

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS channels (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT NOT NULL,
        type            TEXT NOT NULL DEFAULT 'direct',
        character_id    TEXT NOT NULL,
        user_id         INTEGER NOT NULL REFERENCES users(id),
        created_at      TEXT NOT NULL,
        last_message_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        external_id  TEXT NOT NULL UNIQUE,
        channel_id   INTEGER NOT NULL REFERENCES channels(id),
        user_id      INTEGER REFERENCES users(id),
        sender_type  TEXT NOT NULL,
        sender_id    TEXT NOT NULL,
        content_type TEXT NOT NULL,
        body         TEXT NOT NULL DEFAULT '',
        media_path   TEXT,
        metadata     TEXT NOT NULL DEFAULT '{}',
        created_at   TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_messages_channel_ts ON messages(channel_id, created_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_ext_id ON messages(external_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_channels_user_name ON channels(user_id, name)",
]

_EXPECTED_COLUMNS: list[tuple[str, str, str]] = [
    # users
    ("users", "name",       "TEXT NOT NULL DEFAULT ''"),
    ("users", "created_at", "TEXT NOT NULL DEFAULT ''"),
    # channels
    ("channels", "name",            "TEXT NOT NULL DEFAULT ''"),
    ("channels", "type",            "TEXT NOT NULL DEFAULT 'direct'"),
    ("channels", "character_id",    "TEXT NOT NULL DEFAULT ''"),
    ("channels", "user_id",         "INTEGER NOT NULL DEFAULT 0"),
    ("channels", "created_at",      "TEXT NOT NULL DEFAULT ''"),
    ("channels", "last_message_at", "TEXT"),
    # messages
    ("messages", "external_id",  "TEXT NOT NULL DEFAULT ''"),
    ("messages", "channel_id",   "INTEGER NOT NULL DEFAULT 0"),
    ("messages", "user_id",      "INTEGER"),
    ("messages", "sender_type",  "TEXT NOT NULL DEFAULT ''"),
    ("messages", "sender_id",    "TEXT NOT NULL DEFAULT ''"),
    ("messages", "content_type", "TEXT NOT NULL DEFAULT ''"),
    ("messages", "body",         "TEXT NOT NULL DEFAULT ''"),
    ("messages", "media_path",   "TEXT"),
    ("messages", "metadata",     "TEXT NOT NULL DEFAULT '{}'"),
    ("messages", "created_at",   "TEXT NOT NULL DEFAULT ''"),
]

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def data_dir(workspace_path: Path) -> Path:
    return workspace_path / DATA_DIR


def data_db_path(workspace_path: Path) -> Path:
    return data_dir(workspace_path) / DATA_DB_FILENAME


def media_dir(workspace_path: Path) -> Path:
    return data_dir(workspace_path) / MEDIA_DIR


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def _migrate_channels_agent_id_to_character_id(conn: sqlite3.Connection) -> None:
    """Rename legacy ``agent_id`` column on channels (Phase 4: character entity).

    Fresh installs create ``character_id`` directly; existing workspaces keep data
    via SQLite ``RENAME COLUMN`` (3.25+).
    """
    cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(channels)")}
    if "character_id" in cols:
        return
    if "agent_id" in cols:
        conn.execute("ALTER TABLE channels RENAME COLUMN agent_id TO character_id")


def ensure_data_db(workspace_path: Path) -> None:
    """Create data.db, upgrade tables, seed defaults (sync, idempotent)."""
    key = str(workspace_path.resolve())
    if key in _initialized:
        return

    data_dir(workspace_path).mkdir(parents=True, exist_ok=True)
    media_dir(workspace_path).mkdir(parents=True, exist_ok=True)

    db = str(data_db_path(workspace_path))
    with sqlite3.connect(db) as conn:
        for ddl in _DDL:
            conn.execute(ddl)

        # Must run before ADD COLUMN logic so we never end up with both names.
        try:
            _migrate_channels_agent_id_to_character_id(conn)
        except sqlite3.OperationalError as exc:
            # Very old SQLite without RENAME COLUMN — surface a clear error.
            log.error(
                "channels migration failed (need SQLite 3.25+ for RENAME COLUMN)",
                error=str(exc),
            )
            raise

        table_existing: dict[str, set[str]] = {}
        for table, col_name, col_def in _EXPECTED_COLUMNS:
            if table not in table_existing:
                table_existing[table] = {
                    row[1] for row in conn.execute(f"PRAGMA table_info({table})")
                }
            if col_name not in table_existing[table]:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                table_existing[table].add(col_name)

        conn.commit()

        _seed_defaults(conn, workspace_path)

    _initialized.add(key)
    log.info("Data store initialized", path=db)


def _seed_defaults(conn: sqlite3.Connection, workspace_path: Path) -> None:
    """Create default user and default channel if they don't exist."""
    now = utc_iso(utc_now())

    # Default user
    conn.execute(
        "INSERT OR IGNORE INTO users (name, created_at) VALUES (?, ?)",
        (_DEFAULT_USER_NAME, now),
    )

    user_row = conn.execute(
        "SELECT id FROM users WHERE name = ?", (_DEFAULT_USER_NAME,)
    ).fetchone()
    user_id = user_row[0]

    from .character import default_character_id

    character_id = default_character_id(workspace_path)

    # Default channel — linked to default user and default character (slug in workspace.db index)
    conn.execute(
        """
        INSERT OR IGNORE INTO channels (name, type, character_id, user_id, created_at)
        VALUES (?, 'direct', ?, ?, ?)
        """,
        (_DEFAULT_CHANNEL_NAME, character_id, user_id, now),
    )
    conn.commit()


def get_default_user_id(workspace_path: Path) -> int:
    """Return the seeded default user id."""
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE name = ?",
            (_DEFAULT_USER_NAME,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Default user is missing from data.db")
        return int(row[0])


