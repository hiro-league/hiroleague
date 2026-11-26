"""The extensions the core installed (``hiro extension install``): one ``installs`` row each in workspace.db, by key.

A row is made once the person approved what the app asks (state ``approving``: their admin step still to come), and
keeps the install's progress: ``waiting`` once the service runs and the app hasn't paired yet, ``running`` once it has,
``failed`` when a step after the admin step failed (``step`` says why; removing it still works), ``removing`` while it
goes. It keeps what the person approved (``consent``), which the app is approved for when it pairs with its install's
code, and the package it installs from until it is unpacked. An app running from its own container has no row: it
shows as not installed by the core.

The install's pairing code is the app's way to pair with no shell: long and random, given in the service's
environment (app.env), bound to this key, and gone once used. Only its hash is kept here; the code itself is never
logged.

All functions are workspace-scoped and synchronous (CLI and admin threads); the runtime calls them from a worker
thread.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from hiro_channel_sdk.approvals import ApprovedItem
from hiro_commons.timestamps import utc_iso

from .db import db_path, ensure_db

TABLE = "installs"

APPROVING = "approving"  # the row is made; the person's admin step (account, service) is still to come
WAITING = "waiting"  # the service runs; the app hasn't paired with its install's code yet
RUNNING = "running"  # the app paired: its extension_records row has the same key
FAILED = "failed"  # a step after the admin step failed: ``step`` says why
REMOVING = "removing"
STATES = (APPROVING, WAITING, RUNNING, FAILED, REMOVING)


@dataclass(frozen=True)
class Install:
    key: str
    kind: str
    title: str
    version: str
    previous_version: str
    port: int | None
    service: str
    account: str
    state: str
    step: str
    home: str  # the Hiro home it was installed under
    installed_at: str
    updated_at: str
    consent: tuple[ApprovedItem, ...] = ()  # what the person approved at install
    package: str = ""  # the stored package it installs from (packages.py), until it is unpacked
    command: str = ""  # the program its service runs (the manifest's command)


class InstallExists(ValueError):
    """The key is installed already (or being installed): the message is for people."""


def new_code() -> str:
    """An install's pairing code: long and random, since it lasts until the app pairs (an admin's code lasts 5 min)."""
    return secrets.token_urlsafe(24)


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _row(row: sqlite3.Row) -> Install:
    return Install(
        key=row["key"], kind=row["kind"], title=row["title"], version=row["version"],
        previous_version=row["previous_version"], port=row["port"], service=row["service"], account=row["account"],
        state=row["state"], step=row["step"], home=row["home"], installed_at=row["installed_at"],
        updated_at=row["updated_at"],
        consent=tuple(ApprovedItem.model_validate(i) for i in json.loads(row["consent"] or "[]")),
        package=row["package"], command=row["command"],
    )


def _connect(workspace_path: Path) -> sqlite3.Connection:
    ensure_db(workspace_path)
    conn = sqlite3.connect(str(db_path(workspace_path)))
    conn.row_factory = sqlite3.Row
    return conn


def list_installs(workspace_path: Path) -> list[Install]:
    with _connect(workspace_path) as conn:
        return [_row(r) for r in conn.execute(f"SELECT * FROM {TABLE} ORDER BY key").fetchall()]


def get_install(workspace_path: Path, key: str) -> Install | None:
    with _connect(workspace_path) as conn:
        row = conn.execute(f"SELECT * FROM {TABLE} WHERE key = ?", (key,)).fetchone()
    return _row(row) if row else None


def add_install(workspace_path: Path, *, key: str, kind: str, title: str, version: str, port: int | None,
                service: str, account: str, home: str, consent: list[ApprovedItem] | tuple[ApprovedItem, ...] = (),
                package: str = "", command: str = "", code: str = "") -> Install:
    """A new install, state ``approving``. Raises InstallExists when the key (or the port) is taken by another row.
    Its pairing code is usually set when the service is about to start (``set_code``)."""
    now = utc_iso(datetime.now(UTC))
    agreed = json.dumps([i.model_dump() for i in consent])
    try:
        with _connect(workspace_path) as conn:
            conn.execute(
                f"INSERT INTO {TABLE} (key, kind, title, version, port, service, account, state, code_hash, home, "
                "installed_at, updated_at, consent, package, command) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "?, ?)",
                (key, kind, title, version, port, service, account, APPROVING, code_hash(code) if code else "", home,
                 now, now, agreed, package, command),
            )
            conn.commit()
    except sqlite3.IntegrityError as exc:
        raise InstallExists(f"“{key}” is installed already, or its port {port} is another install's.") from exc
    found = get_install(workspace_path, key)
    assert found is not None  # noqa: S101 — just written
    return found


def set_state(workspace_path: Path, key: str, state: str, *, step: str = "") -> None:
    if state not in STATES:
        raise ValueError(f"unknown install state {state!r}")
    with _connect(workspace_path) as conn:
        conn.execute(f"UPDATE {TABLE} SET state = ?, step = ?, updated_at = ? WHERE key = ?",
                     (state, step, utc_iso(datetime.now(UTC)), key))
        conn.commit()


def set_code(workspace_path: Path, key: str, code: str) -> None:
    """The install's pairing code, given to the app in its environment: only its hash is kept."""
    with _connect(workspace_path) as conn:
        conn.execute(f"UPDATE {TABLE} SET code_hash = ?, updated_at = ? WHERE key = ?",
                     (code_hash(code), utc_iso(datetime.now(UTC)), key))
        conn.commit()


def set_package(workspace_path: Path, key: str, package: str) -> None:
    with _connect(workspace_path) as conn:
        conn.execute(f"UPDATE {TABLE} SET package = ?, updated_at = ? WHERE key = ?",
                     (package, utc_iso(datetime.now(UTC)), key))
        conn.commit()


def remove_install(workspace_path: Path, key: str) -> bool:
    with _connect(workspace_path) as conn:
        gone = conn.execute(f"DELETE FROM {TABLE} WHERE key = ?", (key,)).rowcount
        conn.commit()
    return gone > 0


def install_for_code(workspace_path: Path, code: str) -> Install | None:
    """The install whose pairing code this is, while it still has one (waiting to pair), else None."""
    wanted = code_hash(code.strip())
    with _connect(workspace_path) as conn:
        rows = conn.execute(f"SELECT * FROM {TABLE} WHERE code_hash != ''").fetchall()
    return next((_row(r) for r in rows if hmac.compare_digest(r["code_hash"], wanted)), None)


def code_used(workspace_path: Path, key: str) -> None:
    """The app paired with its install's code: the code is gone, and the install runs."""
    # Fix: the step kept saying "Waiting for the app to pair" once it had paired (seen on the PC, Nov 26, 2026)
    with _connect(workspace_path) as conn:
        conn.execute(f"UPDATE {TABLE} SET code_hash = '', state = ?, step = '', updated_at = ? WHERE key = ?",
                     (RUNNING, utc_iso(datetime.now(UTC)), key))
        conn.commit()
