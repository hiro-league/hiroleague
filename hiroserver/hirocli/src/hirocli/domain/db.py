"""Workspace database module.

Manages workspace.db (SQLite) — the authoritative store for system config
entities: characters, devices, the extensions (channel plugins and apps). User
content (channels, messages) lives in data.db — see domain/data_store.py.

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

import json
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from hiro_commons.constants.storage import DB_DIR, WORKSPACE_DB_FILENAME

from .core_features import CORE_SOURCE, every_core_key

_log = logging.getLogger(__name__)

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
        device_name        TEXT,
        person_id          TEXT NOT NULL DEFAULT ''
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
    # Unread since the one extension manager: extension_records holds the channel plugins and the apps. These two
    # stay as they were at the copy (_copy_into_extension_records), so the previous release finds its data.
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
        position    INTEGER NOT NULL DEFAULT 0,
        admin       INTEGER NOT NULL DEFAULT 0,
        says        TEXT NOT NULL DEFAULT '',
        rights      TEXT NOT NULL DEFAULT '{}'
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
    # Each app's LAN names (docs/site-names-design.md): its main one, claimed from its address setting, and the extra
    # ones the owner adds beside it (extra = 1); announced and proxied by the core (runtime/site_names.py). Kept until
    # the app or the owner drops it, or the app is removed.
    """
    CREATE TABLE IF NOT EXISTS site_names (
        name          TEXT PRIMARY KEY,
        extension_id  TEXT NOT NULL,
        port          INTEGER NOT NULL,
        claimed_at    TEXT NOT NULL DEFAULT '',
        extra         INTEGER NOT NULL DEFAULT 0
    )
    """,
    # The sites the owner adds that are no app (hiro sites add): a name or the machine's address, its target on this
    # machine (empty = the name is only announced) and the paths it is limited to (a JSON list; empty = all). Kept
    # until the owner removes it.
    """
    CREATE TABLE IF NOT EXISTS other_sites (
        name      TEXT PRIMARY KEY,
        target    TEXT NOT NULL DEFAULT '',
        paths     TEXT NOT NULL DEFAULT '[]',
        added_at  TEXT NOT NULL DEFAULT ''
    )
    """,
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
    # Permissions phase 1: the roles each person holds; their rights add up. people.role_id stays, the first of
    # these in the roles' order (domain/people.py). Kept until the role is taken away or the person is removed.
    """
    CREATE TABLE IF NOT EXISTS person_roles (
        person_id  TEXT NOT NULL,
        role_id    TEXT NOT NULL,
        PRIMARY KEY (person_id, role_id)
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
    # "Sign in with Home Assistant", run by the core (domain/home_assistant_sign_in.py): one row, the address the core
    # reaches HA at and the one people's browsers use, the access token (never answered or logged, as an app keeps its
    # HA token: the live core's keyring is locked without a login session), the owner's switch and the last good
    # connection test. Per place (data.toml). Kept until the owner disconnects it.
    """
    CREATE TABLE IF NOT EXISTS ha_sign_in (
        id            INTEGER PRIMARY KEY CHECK (id = 1),
        address       TEXT NOT NULL DEFAULT '',
        link_address  TEXT NOT NULL DEFAULT '',
        token         TEXT NOT NULL DEFAULT '',
        enabled       INTEGER NOT NULL DEFAULT 0,
        version       TEXT NOT NULL DEFAULT '',
        checked_at    TEXT NOT NULL DEFAULT ''
    )
    """,
    # Who is who: each Home Assistant person with a login, the family person the owner linked it to ('' = nobody: it
    # can't sign in) and the one suggested by name (only a suggestion: it signs nobody in). Refreshed by each
    # connection test; a login gone from Home Assistant is dropped then.
    """
    CREATE TABLE IF NOT EXISTS ha_logins (
        ha_user_id    TEXT PRIMARY KEY,
        name          TEXT NOT NULL DEFAULT '',
        login         TEXT NOT NULL DEFAULT '',
        person_id     TEXT NOT NULL DEFAULT '',
        suggested_id  TEXT NOT NULL DEFAULT ''
    )
    """,
    # Permissions phase 8: a person's proof, given to one app at a sign-in (person_tokens.py); only its hash is kept.
    # Kept while used (90 days unused ends it), until the person signs out of the app, is removed or changes their
    # password; ended ones are dropped at each new one.
    """
    CREATE TABLE IF NOT EXISTS person_tokens (
        token_hash    TEXT PRIMARY KEY,
        person_id     TEXT NOT NULL,
        extension_id  TEXT NOT NULL,
        created_at    TEXT NOT NULL,
        last_used     TEXT NOT NULL,
        expires_at    TEXT NOT NULL
    )
    """,
    # The extensions the core installed (Installing apps, phase 5: hiro extension install), one row each by key: its
    # version and the one before, its port (one install per port), its service and account, its state (approving,
    # waiting: not paired yet, running, upgrading, failed, removing), the hash of its install's pairing code until the app pairs,
    # its current step (or why it failed), the program its service runs, what the person approved at install (consent, a JSON list of
    # {permission, subject}), the package it installs from until it is unpacked, and an upgrade's target version and
    # its copy of the data (the stamp restore puts back) while it runs. An extension_records row joins it
    # by the key once the app pairs. Kept until removed.
    """
    CREATE TABLE IF NOT EXISTS installs (
        key               TEXT PRIMARY KEY,
        kind              TEXT NOT NULL DEFAULT 'app',
        title             TEXT NOT NULL DEFAULT '',
        version           TEXT NOT NULL DEFAULT '',
        previous_version  TEXT NOT NULL DEFAULT '',
        port              INTEGER UNIQUE,
        service           TEXT NOT NULL DEFAULT '',
        account           TEXT NOT NULL DEFAULT '',
        state             TEXT NOT NULL DEFAULT '',
        step              TEXT NOT NULL DEFAULT '',
        code_hash         TEXT NOT NULL DEFAULT '',
        home              TEXT NOT NULL DEFAULT '',
        installed_at      TEXT NOT NULL DEFAULT '',
        updated_at        TEXT NOT NULL DEFAULT '',
        consent           TEXT NOT NULL DEFAULT '[]',
        package           TEXT NOT NULL DEFAULT '',
        command           TEXT NOT NULL DEFAULT '',
        upgrade_to        TEXT NOT NULL DEFAULT '',
        upgrade_stamp     TEXT NOT NULL DEFAULT ''
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
    # Permissions phase 3: the person the device belongs to (a device several people use belongs to a person made
    # for it). "" only before phase 3's first start, which makes those devices the owner's.
    ("devices", "person_id",         "TEXT NOT NULL DEFAULT ''"),
    # channel_plugins
    ("channel_plugins", "enabled",       "INTEGER NOT NULL DEFAULT 1"),
    ("channel_plugins", "command",       "TEXT NOT NULL DEFAULT '[]'"),
    ("channel_plugins", "config",        "TEXT NOT NULL DEFAULT '{}'"),
    ("channel_plugins", "workspace_dir", "TEXT NOT NULL DEFAULT ''"),
    # extension_records (the one extension manager's list); created by _copy_into_extension_records
    ("extension_records", "name",            "TEXT NOT NULL DEFAULT ''"),
    ("extension_records", "kind",            "TEXT NOT NULL DEFAULT 'app'"),
    ("extension_records", "public_key",      "TEXT NOT NULL DEFAULT ''"),
    ("extension_records", "paired_at",       "TEXT NOT NULL DEFAULT ''"),
    ("extension_records", "last_seen",       "TEXT"),
    ("extension_records", "info",            "TEXT NOT NULL DEFAULT '{}'"),
    ("extension_records", "uses_before",     "TEXT NOT NULL DEFAULT '[]'"),
    # Permissions phase 8: the items the owner approved (JSON list of {permission, subject}); NULL = an app paired
    # before approvals, approved for everything until it first declares what it asks (approvals.py)
    ("extension_records", "approved",        "TEXT"),
    # ... and the LAN name and port it last asked for and wasn't approved for ("name:port"; "" = none)
    ("extension_records", "asked_claim",     "TEXT NOT NULL DEFAULT ''"),
    # ... and the optional items the owner left off (JSON list of {permission, subject}): they wait no more
    ("extension_records", "declined",        "TEXT NOT NULL DEFAULT '[]'"),
    ("extension_records", "relays_chat",     "INTEGER NOT NULL DEFAULT 0"),
    ("extension_records", "started_by_core", "INTEGER NOT NULL DEFAULT 0"),
    ("extension_records", "enabled",         "INTEGER NOT NULL DEFAULT 1"),
    ("extension_records", "command",         "TEXT NOT NULL DEFAULT '[]'"),
    ("extension_records", "config",          "TEXT NOT NULL DEFAULT '{}'"),
    ("extension_records", "workspace_dir",   "TEXT NOT NULL DEFAULT ''"),
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
    # site_names (each app's LAN name)
    ("site_names", "extension_id", "TEXT NOT NULL DEFAULT ''"),
    ("site_names", "port",         "INTEGER NOT NULL DEFAULT 0"),
    ("site_names", "claimed_at",   "TEXT NOT NULL DEFAULT ''"),
    # Installing apps, phase 4: a name the owner added beside the app's main one.
    ("site_names", "extra",        "INTEGER NOT NULL DEFAULT 0"),
    # roles, people, admin_sessions (Phase 6)
    ("roles", "name",     "TEXT NOT NULL DEFAULT ''"),
    ("roles", "built_in", "INTEGER NOT NULL DEFAULT 0"),
    ("roles", "position", "INTEGER NOT NULL DEFAULT 0"),
    # Phase 8: the role can open HiroLeague's settings (Owner always can; domain/people.py).
    ("roles", "admin",    "INTEGER NOT NULL DEFAULT 0"),
    # Phase 9a: one line on what the role is for, and the rights it has in each extension (JSON {extension: [keys]}).
    ("roles", "says",     "TEXT NOT NULL DEFAULT ''"),
    ("roles", "rights",   "TEXT NOT NULL DEFAULT '{}'"),
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
    ("ha_sign_in", "address",      "TEXT NOT NULL DEFAULT ''"),
    ("ha_sign_in", "link_address", "TEXT NOT NULL DEFAULT ''"),
    ("ha_sign_in", "token",        "TEXT NOT NULL DEFAULT ''"),
    ("ha_sign_in", "enabled",      "INTEGER NOT NULL DEFAULT 0"),
    ("ha_sign_in", "version",      "TEXT NOT NULL DEFAULT ''"),
    ("ha_sign_in", "checked_at",   "TEXT NOT NULL DEFAULT ''"),
    ("ha_logins", "name",          "TEXT NOT NULL DEFAULT ''"),
    ("ha_logins", "login",         "TEXT NOT NULL DEFAULT ''"),
    ("ha_logins", "person_id",     "TEXT NOT NULL DEFAULT ''"),
    ("ha_logins", "suggested_id",  "TEXT NOT NULL DEFAULT ''"),
    ("installs", "kind",           "TEXT NOT NULL DEFAULT 'app'"),
    ("installs", "title",          "TEXT NOT NULL DEFAULT ''"),
    ("installs", "version",        "TEXT NOT NULL DEFAULT ''"),
    ("installs", "previous_version", "TEXT NOT NULL DEFAULT ''"),
    ("installs", "port",           "INTEGER"),
    ("installs", "service",        "TEXT NOT NULL DEFAULT ''"),
    ("installs", "account",        "TEXT NOT NULL DEFAULT ''"),
    ("installs", "state",          "TEXT NOT NULL DEFAULT ''"),
    ("installs", "step",           "TEXT NOT NULL DEFAULT ''"),
    ("installs", "code_hash",      "TEXT NOT NULL DEFAULT ''"),
    ("installs", "home",           "TEXT NOT NULL DEFAULT ''"),
    ("installs", "installed_at",   "TEXT NOT NULL DEFAULT ''"),
    ("installs", "updated_at",     "TEXT NOT NULL DEFAULT ''"),
    ("installs", "consent",        "TEXT NOT NULL DEFAULT '[]'"),
    ("installs", "package",        "TEXT NOT NULL DEFAULT ''"),
    ("installs", "command",        "TEXT NOT NULL DEFAULT ''"),
    ("installs", "upgrade_to",     "TEXT NOT NULL DEFAULT ''"),
    ("installs", "upgrade_stamp",  "TEXT NOT NULL DEFAULT ''"),
]


# The one extension manager's list: every channel plugin and app, one row each. Kept until Michel removes the
# extension. Created, with its rows copied from extensions and channel_plugins, in one transaction.
_EXTENSION_RECORDS_DDL = """
    CREATE TABLE extension_records (
        extension_id    TEXT PRIMARY KEY,
        name            TEXT NOT NULL DEFAULT '',
        kind            TEXT NOT NULL DEFAULT 'app',
        public_key      TEXT NOT NULL DEFAULT '',
        paired_at       TEXT NOT NULL DEFAULT '',
        last_seen       TEXT,
        info            TEXT NOT NULL DEFAULT '{}',
        uses_before     TEXT NOT NULL DEFAULT '[]',
        relays_chat     INTEGER NOT NULL DEFAULT 0,
        started_by_core INTEGER NOT NULL DEFAULT 0,
        enabled         INTEGER NOT NULL DEFAULT 1,
        command         TEXT NOT NULL DEFAULT '[]',
        config          TEXT NOT NULL DEFAULT '{}',
        workspace_dir   TEXT NOT NULL DEFAULT ''
    )
"""
# An extension the core starts is one per name.
_EXTENSION_RECORDS_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS extension_records_started_name "
    "ON extension_records (name) WHERE started_by_core = 1"
)


class ExtensionCopyError(RuntimeError):
    """The copy into extension_records didn't hold every row: nothing was written."""


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Add any column in _EXPECTED_COLUMNS that its table lacks (a table not made yet is skipped)."""
    table_existing: dict[str, set[str]] = {}
    for table, col_name, col_def in _EXPECTED_COLUMNS:
        if table not in table_existing:
            table_existing[table] = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not table_existing[table]:
            continue  # not created yet
        if col_name not in table_existing[table]:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
            table_existing[table].add(col_name)


def _copy_into_extension_records(conn: sqlite3.Connection) -> tuple[int, int] | None:
    """Make extension_records the first time, holding every row of extensions (apps, their ids and keys kept) and of
    channel_plugins (channel plugins: a new id, no key yet; each pairs at its first start).

    One transaction: the table, its rows, then the counts compared; on a mismatch it is rolled back and nothing is
    left. extensions and channel_plugins are only read. Returns (apps, channels) copied, or None when the table was
    already there.
    """
    if _table_exists(conn, "extension_records"):
        return None
    conn.execute("BEGIN IMMEDIATE")
    try:
        if _table_exists(conn, "extension_records"):  # another process made it meanwhile
            conn.execute("ROLLBACK")
            return None
        conn.execute(_EXTENSION_RECORDS_DDL)
        conn.execute(_EXTENSION_RECORDS_INDEX)
        conn.execute(
            """
            INSERT INTO extension_records
                (extension_id, name, kind, public_key, paired_at, last_seen, info, uses_before,
                 relays_chat, started_by_core, enabled)
            SELECT extension_id, name, 'app', public_key, paired_at, last_seen, info, uses_before, 0, 0, 1
            FROM extensions
            """
        )
        conn.execute(
            """
            INSERT INTO extension_records
                (extension_id, name, kind, public_key, paired_at, info,
                 relays_chat, started_by_core, enabled, command, config, workspace_dir)
            SELECT lower(hex(randomblob(16))), name, 'channel', '', '', '{}', 1, 1, enabled, command, config, workspace_dir
            FROM channel_plugins
            """
        )
        apps = conn.execute("SELECT COUNT(*) FROM extensions").fetchone()[0]
        channels = conn.execute("SELECT COUNT(*) FROM channel_plugins").fetchone()[0]
        copied_apps = conn.execute(
            "SELECT COUNT(*) FROM extension_records r JOIN extensions e ON e.extension_id = r.extension_id "
            "AND e.public_key = r.public_key WHERE r.kind = 'app'"
        ).fetchone()[0]
        copied_channels = conn.execute(
            "SELECT COUNT(*) FROM extension_records r JOIN channel_plugins c ON c.name = r.name "
            "AND c.config = r.config AND c.enabled = r.enabled WHERE r.kind = 'channel'"
        ).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM extension_records").fetchone()[0]
        if (copied_apps, copied_channels, total) != (apps, channels, apps + channels):
            raise ExtensionCopyError(
                f"extension_records would hold {copied_apps}/{apps} apps and {copied_channels}/{channels} channel "
                f"plugins ({total} rows): rolled back"
            )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return apps, channels


def _fill_person_roles(conn: sqlite3.Connection) -> int:
    """Each person who holds no role in person_roles yet gets one row: the role in their people.role_id.

    people and roles are read, never written, so it is safe to run on every start: a person added by an older
    release, which knew only people.role_id, is filled on the next. This release always keeps people.role_id one of a
    person's rows; when it isn't, an older release run by hand on this database changed their role, so their rows are
    dropped and they hold that one role, as the older release meant. Returns how many people were filled.
    """
    conn.execute(
        """
        DELETE FROM person_roles WHERE person_id IN (
            SELECT p.person_id FROM people p WHERE p.role_id != ''
            AND NOT EXISTS (SELECT 1 FROM person_roles pr WHERE pr.person_id = p.person_id AND pr.role_id = p.role_id)
        )
        """
    )
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO person_roles (person_id, role_id)
        SELECT p.person_id, p.role_id FROM people p
        WHERE p.role_id != '' AND NOT EXISTS (SELECT 1 FROM person_roles pr WHERE pr.person_id = p.person_id)
        """
    )
    return max(cur.rowcount, 0)


def _give_core_to_admin_roles(conn: sqlite3.Connection) -> list[str]:
    """Permissions phase 2, once per role: a role whose Phase 8 admin switch is on, and that holds nothing in the
    core yet, gets every core permission, so nobody who opened the admin loses a page. A role with any core grants
    (even none, set on the Roles page) is never touched again, and Owner needs none. Returns the role ids given them.
    """
    given: list[str] = []
    rows = conn.execute("SELECT role_id, rights FROM roles WHERE admin = 1 AND role_id != 'owner'").fetchall()
    for role_id, raw in rows:
        try:
            rights = json.loads(raw or "{}")
        except json.JSONDecodeError:
            _log.warning("Roles: %s's rights can't be read; its core permissions are left as they are", role_id)
            continue
        if not isinstance(rights, dict) or CORE_SOURCE in rights:
            continue
        rights[CORE_SOURCE] = every_core_key()
        conn.execute("UPDATE roles SET rights = ? WHERE role_id = ?", (json.dumps(rights), role_id))
        given.append(str(role_id))
    return given


def _give_devices_to_owner(conn: sqlite3.Connection) -> int:
    """Permissions phase 3: every paired device that belongs to nobody becomes the owner's (the first person who holds
    Owner), as every conversation made before phase 3 is. A device paired since always names its person, so this
    finds devices only on phase 3's first start. With no owner in the family list yet, they wait for one. Returns how
    many devices were given."""
    owner = conn.execute(
        """
        SELECT p.person_id FROM people p JOIN person_roles pr ON pr.person_id = p.person_id
        WHERE pr.role_id = 'owner' ORDER BY p.created_at, p.person_id LIMIT 1
        """
    ).fetchone()
    if owner is None:
        return 0
    cur = conn.execute("UPDATE devices SET person_id = ? WHERE person_id = ''", (owner[0],))
    return max(cur.rowcount, 0)


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

    # isolation_level=None: each statement commits by itself, and the copy runs its own transaction.
    conn = sqlite3.connect(str(db_path(workspace_path)), isolation_level=None)
    try:
        for ddl in _DDL:
            conn.execute(ddl)
        _add_missing_columns(conn)
        copied = _copy_into_extension_records(conn)
        _add_missing_columns(conn)
        filled = _fill_person_roles(conn)
        given = _give_core_to_admin_roles(conn)
        devices = _give_devices_to_owner(conn)
    finally:
        conn.close()
    if devices:
        _log.info("Devices: %d paired device(s) now belong to the owner (Permissions phase 3)", devices)
    if given:
        _log.info("Roles: %s opened the admin, and now hold every core permission (Permissions phase 2)", ", ".join(given))
    if filled:
        _log.info("People: %d person(s) now hold their role in person_roles (Permissions phase 1)", filled)
    if copied is not None:
        _log.info(
            "Extensions: the one list was made — %d app(s) and %d channel plugin(s) copied, counts match",
            copied[0],
            copied[1],
        )

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
