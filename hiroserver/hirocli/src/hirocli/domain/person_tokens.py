"""A person's proof, given to one app (Permissions phase 8, "What an app is approved for: the design").

When the core signs someone in for an app (the one sign-in's ``auth.code``), it gives that app a token for that
person. The app sends it with each ask a page makes for that person (``_signed_in``), and the core answers by that
person's own rights. A token is good only from the app it was given to. Only its SHA-256 is kept, as the admin's
own sessions are (admin_sign_in.py). It lasts while it is used: each use moves its end on (at most once an hour),
and 90 days unused ends it; signing out of the app, being removed or a new password end it at once (people.py).
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hiro_commons.timestamps import utc_iso

from .db import db_path, ensure_db

TOKEN_DAYS = 90
TOUCH_EVERY = timedelta(hours=1)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _connect(workspace_path: Path) -> sqlite3.Connection:
    ensure_db(workspace_path)
    return sqlite3.connect(str(db_path(workspace_path)))


def issue(workspace_path: Path, person_id: str, extension_id: str) -> str:
    """A new proof of ``person_id`` for one app; ended ones are dropped meanwhile."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    with _connect(workspace_path) as conn:
        conn.execute("DELETE FROM person_tokens WHERE expires_at < ?", (utc_iso(now),))
        conn.execute(
            "INSERT INTO person_tokens (token_hash, person_id, extension_id, created_at, last_used, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_hash(token), person_id, extension_id, utc_iso(now), utc_iso(now), utc_iso(now + timedelta(days=TOKEN_DAYS))),
        )
        conn.commit()
    return token


def person_of(workspace_path: Path, token: str, extension_id: str) -> str | None:
    """The person a proof stands for, when it was given to this app and hasn't ended; its end moves on with use."""
    if not token:
        return None
    now = datetime.now(UTC)
    with _connect(workspace_path) as conn:
        row = conn.execute(
            "SELECT person_id, extension_id, last_used, expires_at FROM person_tokens WHERE token_hash = ?",
            (_hash(token),),
        ).fetchone()
        if row is None or row[1] != extension_id or row[3] < utc_iso(now):
            return None
        if now - datetime.fromisoformat(row[2]) >= TOUCH_EVERY:
            conn.execute(
                "UPDATE person_tokens SET last_used = ?, expires_at = ? WHERE token_hash = ?",
                (utc_iso(now), utc_iso(now + timedelta(days=TOKEN_DAYS)), _hash(token)),
            )
            conn.commit()
    return str(row[0])


def end(workspace_path: Path, token: str, extension_id: str) -> None:
    """The person signed out of the app: its proof ends (only the app it was given to can end it)."""
    with _connect(workspace_path) as conn:
        conn.execute("DELETE FROM person_tokens WHERE token_hash = ? AND extension_id = ?", (_hash(token), extension_id))
        conn.commit()


def end_for_app(workspace_path: Path, extension_id: str) -> None:
    """The app was removed: every proof it held ends."""
    with _connect(workspace_path) as conn:
        conn.execute("DELETE FROM person_tokens WHERE extension_id = ?", (extension_id,))
        conn.commit()
