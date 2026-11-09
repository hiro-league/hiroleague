"""Workspace database module.

Manages workspace.db (SQLite) — the authoritative store for system config
entities: characters, devices, channel_plugins. User content (channels, messages)
lives in data.db — see domain/data_store.py.

Two interfaces are provided:
- ensure_db / db_path — synchronous helpers used by domain functions and CLI
  commands that run outside an async context.
- init_db / get_db — async interface (aiosqlite) used at server startup and
  wherever a long-lived async connection is needed (e.g. LangGraph checkpointer
  wiring in server_process.py).

Schema evolution policy
-----------------------
Both ensure_db and init_db run two passes on first call per process:

1. CREATE TABLE IF NOT EXISTS — creates all tables on a fresh database.
2. PRAGMA table_info + ALTER TABLE ADD COLUMN — adds any column listed in
   _EXPECTED_COLUMNS that is absent from the actual table.

To add a column: append one entry to _EXPECTED_COLUMNS and to the matching
CREATE TABLE statement. Never remove entries from _EXPECTED_COLUMNS — old
databases are upgraded automatically on next startup, no version counter needed.

Every new column must be nullable or have a DEFAULT so ALTER TABLE succeeds on
existing rows.  Enforce NOT NULL without a default only on primary keys and
columns always set by application code at insert time.
"""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from hiro_commons.constants.storage import DB_DIR, WORKSPACE_DB_FILENAME

# Per-process cache: paths for which ensure_db has already run successfully.
# Keyed by the resolved string workspace path.
_initialized: set[str] = set()

# ---------------------------------------------------------------------------
# DDL — CREATE TABLE statements for fresh databases
# ---------------------------------------------------------------------------

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS characters (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        is_default  INTEGER NOT NULL DEFAULT 0,
        folder_path TEXT NOT NULL,
        created_at  TEXT NOT NULL DEFAULT '',
        updated_at  TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS devices (
        device_id          TEXT PRIMARY KEY,
        device_public_key  TEXT NOT NULL,
        paired_at          TEXT NOT NULL,
        expires_at         TEXT,
        metadata           TEXT NOT NULL DEFAULT '{}',
        device_name        TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS channel_plugins (
        name          TEXT PRIMARY KEY,
        enabled       INTEGER NOT NULL DEFAULT 1,
        command       TEXT NOT NULL DEFAULT '[]',
        config        TEXT NOT NULL DEFAULT '{}',
        workspace_dir TEXT NOT NULL DEFAULT ''
    )
    """,
    # Paired extensions (programs that sign in on the extension socket, HomeHiro
    # first): the public half of each one's key, and what it last said about itself.
    """
    CREATE TABLE IF NOT EXISTS extensions (
        extension_id  TEXT PRIMARY KEY,
        name          TEXT NOT NULL DEFAULT '',
        public_key    TEXT NOT NULL,
        paired_at     TEXT NOT NULL,
        last_seen     TEXT,
        info          TEXT NOT NULL DEFAULT '{}',
        uses_before   TEXT NOT NULL DEFAULT '[]'
    )
    """,
    # The family (the plan's Phase 6): one list, owned by the core; extensions (HomeHiro)
    # read it. sign_in/password_hash are set only for people who use the admin.
    """
    CREATE TABLE IF NOT EXISTS roles (
        role_id     TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        built_in    INTEGER NOT NULL DEFAULT 0,
        position    INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS people (
        person_id      TEXT PRIMARY KEY,
        name           TEXT NOT NULL,
        calls_them     TEXT NOT NULL DEFAULT '',
        whatsapp       TEXT NOT NULL DEFAULT '',
        role_id        TEXT NOT NULL,
        sign_in        TEXT,
        password_hash  TEXT,
        created_at     TEXT NOT NULL DEFAULT '',
        updated_at     TEXT NOT NULL DEFAULT ''
    )
    """,
    # Phase 7b: every paid AI call, per clock hour (UTC hour start) × kind, source, use, profile,
    # provider, model, billing, person, label and result — the AI usage page and each AI profile's
    # limits read it; kept for good (services/ai_usage/store.py). It replaces 7a's ai_usage
    # (profile × hour only), dropped here: no migration (initial development).
    "DROP TABLE IF EXISTS ai_usage",
    """
    CREATE TABLE IF NOT EXISTS ai_calls (
        hour          TEXT NOT NULL,
        kind          TEXT NOT NULL,
        source        TEXT NOT NULL,
        use_id        TEXT NOT NULL DEFAULT '',
        profile_id    TEXT NOT NULL DEFAULT '',
        provider      TEXT NOT NULL DEFAULT '',
        model         TEXT NOT NULL DEFAULT '',
        billing       TEXT NOT NULL DEFAULT 'api',
        person_id     TEXT NOT NULL DEFAULT '',
        label         TEXT NOT NULL DEFAULT '',
        result        TEXT NOT NULL DEFAULT 'ok',
        profile_name  TEXT NOT NULL DEFAULT '',
        requests      INTEGER NOT NULL DEFAULT 0,
        tokens_in     INTEGER NOT NULL DEFAULT 0,
        tokens_out    INTEGER NOT NULL DEFAULT 0,
        ms            INTEGER NOT NULL DEFAULT 0,
        cost          REAL NOT NULL DEFAULT 0,
        estimate      REAL NOT NULL DEFAULT 0,
        unpriced      INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (hour, kind, source, use_id, profile_id, provider, model, billing, person_id, label, result)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ai_calls_profile_hour ON ai_calls (profile_id, hour)",
    # Phase 7a: the models a local server (LM Studio / Ollama) last reported, so AI profiles can
    # point at them without catalog rows and still read while the PC is off.
    """
    CREATE TABLE IF NOT EXISTS local_models (
        provider_id  TEXT NOT NULL,
        name         TEXT NOT NULL,
        display_name TEXT NOT NULL DEFAULT '',
        vision       INTEGER NOT NULL DEFAULT 0,
        reasoning    INTEGER NOT NULL DEFAULT 0,
        loaded       INTEGER NOT NULL DEFAULT 0,
        seen_at      TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (provider_id, name)
    )
    """,
    # Admin sign-in sessions: only a hash of each cookie's token is kept.
    """
    CREATE TABLE IF NOT EXISTS admin_sessions (
        token_hash  TEXT PRIMARY KEY,
        person_id   TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        expires_at  TEXT NOT NULL
    )
    """,
]

# ---------------------------------------------------------------------------
# Expected columns — drives the introspection-based upgrade pass
#
# List every non-primary-key column for every table.
# Each entry: (table_name, column_name, ALTER TABLE compatible definition)
#
# Rules:
# - Never remove an entry — old databases are upgraded on next startup.
# - Every definition must be nullable or have a DEFAULT (required for
#   ALTER TABLE ADD COLUMN on existing rows).
# - When adding a new column: append here AND to the CREATE TABLE above.
# ---------------------------------------------------------------------------

_EXPECTED_COLUMNS: list[tuple[str, str, str]] = [
    # characters — relational index; persona text lives in workspace characters/<id>/
    ("characters", "name",        "TEXT NOT NULL DEFAULT ''"),
    ("characters", "is_default",  "INTEGER NOT NULL DEFAULT 0"),
    ("characters", "folder_path", "TEXT NOT NULL DEFAULT ''"),
    ("characters", "created_at",  "TEXT NOT NULL DEFAULT ''"),
    ("characters", "updated_at",  "TEXT NOT NULL DEFAULT ''"),
    # devices
    ("devices", "device_public_key", "TEXT NOT NULL DEFAULT ''"),
    ("devices", "paired_at",         "TEXT NOT NULL DEFAULT ''"),
    ("devices", "expires_at",        "TEXT"),
    ("devices", "metadata",          "TEXT NOT NULL DEFAULT '{}'"),
    ("devices", "device_name",       "TEXT"),
    # channel_plugins
    ("channel_plugins", "enabled",       "INTEGER NOT NULL DEFAULT 1"),
    ("channel_plugins", "command",       "TEXT NOT NULL DEFAULT '[]'"),
    ("channel_plugins", "config",        "TEXT NOT NULL DEFAULT '{}'"),
    ("channel_plugins", "workspace_dir", "TEXT NOT NULL DEFAULT ''"),
    # extensions
    ("extensions", "name",       "TEXT NOT NULL DEFAULT ''"),
    ("extensions", "public_key", "TEXT NOT NULL DEFAULT ''"),
    ("extensions", "paired_at",  "TEXT NOT NULL DEFAULT ''"),
    ("extensions", "last_seen",  "TEXT"),
    ("extensions", "info",       "TEXT NOT NULL DEFAULT '{}'"),
    # Phase 7a: the use ids the extension declared before its last change (Uses page: "new").
    ("extensions", "uses_before", "TEXT NOT NULL DEFAULT '[]'"),
    # ai_calls (Phase 7b): answered calls counted at $0 for want of a price
    ("ai_calls", "unpriced", "INTEGER NOT NULL DEFAULT 0"),
    # local_models (Phase 7a); 7a's ai_usage is dropped (Phase 7b: ai_calls)
    ("local_models", "display_name", "TEXT NOT NULL DEFAULT ''"),
    ("local_models", "vision",       "INTEGER NOT NULL DEFAULT 0"),
    ("local_models", "reasoning",    "INTEGER NOT NULL DEFAULT 0"),
    ("local_models", "loaded",       "INTEGER NOT NULL DEFAULT 0"),
    ("local_models", "seen_at",      "TEXT NOT NULL DEFAULT ''"),
    # roles, people, admin_sessions (Phase 6)
    ("roles", "name",     "TEXT NOT NULL DEFAULT ''"),
    ("roles", "built_in", "INTEGER NOT NULL DEFAULT 0"),
    ("roles", "position", "INTEGER NOT NULL DEFAULT 0"),
    ("people", "name",          "TEXT NOT NULL DEFAULT ''"),
    ("people", "calls_them",    "TEXT NOT NULL DEFAULT ''"),
    ("people", "whatsapp",      "TEXT NOT NULL DEFAULT ''"),
    ("people", "role_id",       "TEXT NOT NULL DEFAULT ''"),
    ("people", "sign_in",       "TEXT"),
    ("people", "password_hash", "TEXT"),
    ("people", "created_at",    "TEXT NOT NULL DEFAULT ''"),
    ("people", "updated_at",    "TEXT NOT NULL DEFAULT ''"),
    ("admin_sessions", "person_id",  "TEXT NOT NULL DEFAULT ''"),
    ("admin_sessions", "created_at", "TEXT NOT NULL DEFAULT ''"),
    ("admin_sessions", "expires_at", "TEXT NOT NULL DEFAULT ''"),
]


# ---------------------------------------------------------------------------
# Path helper
# ---------------------------------------------------------------------------

def db_path(workspace_path: Path) -> Path:
    """Return the absolute path to workspace.db inside *workspace_path*."""
    # All DBs live under <workspace>/db/ (consolidated layout) — see storage.DB_DIR.
    return workspace_path / DB_DIR / WORKSPACE_DB_FILENAME


# ---------------------------------------------------------------------------
# Synchronous interface — used by domain functions and CLI commands
# ---------------------------------------------------------------------------

def ensure_db(workspace_path: Path) -> None:
    """Create workspace.db, upgrade all tables, and ensure subdirectories (sync, idempotent).

    Runs the full setup only once per process per workspace path.  Subsequent
    calls are a no-op so calling ensure_db at the top of every domain function
    has no measurable overhead in production.

    Pass 1: CREATE TABLE IF NOT EXISTS for fresh databases.
    Pass 2: PRAGMA table_info + ALTER TABLE ADD COLUMN for existing databases
            that are missing columns introduced after initial creation.
    """
    key = str(workspace_path.resolve())
    if key in _initialized:
        return

    # Ensure the consolidated db/ folder exists before SQLite opens the file.
    db_path(workspace_path).parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        for ddl in _DDL:
            conn.execute(ddl)

        # Add any columns that exist in _EXPECTED_COLUMNS but not in the table.
        # PRAGMA table_info is called once per table, not once per column.
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

    _initialized.add(key)


# ---------------------------------------------------------------------------
# Async interface — used by the server process and LangGraph checkpointer
# ---------------------------------------------------------------------------

async def init_db(workspace_path: Path) -> aiosqlite.Connection:
    """Open workspace.db, ensure all tables exist, and return the open connection.

    Calls ensure_db synchronously first (fast — no-op after the first call per
    process) then opens the aiosqlite connection for async callers.

    The caller is responsible for closing the connection.
    Prefer get_db() as an async context manager for automatic cleanup.
    """
    ensure_db(workspace_path)
    return await aiosqlite.connect(str(db_path(workspace_path)))


@asynccontextmanager
async def get_db(workspace_path: Path):
    """Async context manager that opens workspace.db, ensures tables, and yields the connection."""
    conn = await init_db(workspace_path)
    try:
        yield conn
    finally:
        await conn.close()
