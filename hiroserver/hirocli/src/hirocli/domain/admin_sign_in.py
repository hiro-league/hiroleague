"""HiroLeague's own admin sign-in: passwords and sessions (the plan's Phase 6).

A name and a password, checked here on the machine: it works on any address and
without internet. The owner's is set from the CLI (``hiro people owner`` /
``hiro workspaces setup``); the owner gives the others theirs in the admin; a
forgotten one is reset from the CLI. Devices and extensions keep their pairing codes.

- Passwords are kept as scrypt hashes (``scrypt$n$r$p$salt$hash``, standard library).
- A session is a random token in an HttpOnly cookie; workspace.db keeps only its
  SHA-256, so a copy of the database can't be used to sign in.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hiro_commons.timestamps import utc_iso

from .db import db_path, ensure_db
from .people import PeopleError, Person, get_person, set_sign_in, sign_in_hash

PASSWORD_MIN = 8
SESSION_DAYS = 30

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
# A hash to check against when the name is unknown, so a wrong name takes as long as a wrong password.
_DUMMY_HASH = ""


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    if len(password or "") < PASSWORD_MIN:
        raise PeopleError(f"The password needs at least {PASSWORD_MIN} characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def password_matches(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        got = hashlib.scrypt(
            (password or "").encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=len(_unb64(digest))
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, _unb64(digest))


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if not _DUMMY_HASH:
        _DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
    return _DUMMY_HASH


def give_sign_in(workspace_path: Path, person_id: str, *, sign_in: str, password: str) -> Person:
    """Set a person's sign-in name and password (new, changed or reset)."""
    return set_sign_in(workspace_path, person_id, sign_in=sign_in, password_hash=hash_password(password))


def check_password(workspace_path: Path, sign_in: str, password: str) -> Person | None:
    """The person when the name and password are right, else None."""
    found = sign_in_hash(workspace_path, sign_in)
    if found is None:
        password_matches(password, _dummy_hash())
        return None
    person, stored = found
    return person if password_matches(password, stored) else None


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _connect(workspace_path: Path) -> sqlite3.Connection:
    ensure_db(workspace_path)
    return sqlite3.connect(str(db_path(workspace_path)))


def start_session(workspace_path: Path, person_id: str) -> tuple[str, datetime]:
    """A new session for a signed-in person: the cookie's token and when it ends."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires = now + timedelta(days=SESSION_DAYS)
    with _connect(workspace_path) as conn:
        # Ended sessions are dropped whenever a new one starts.
        conn.execute("DELETE FROM admin_sessions WHERE expires_at < ?", (utc_iso(now),))
        conn.execute(
            "INSERT INTO admin_sessions (token_hash, person_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (_token_hash(token), person_id, utc_iso(now), utc_iso(expires)),
        )
        conn.commit()
    return token, expires


def session_person(workspace_path: Path, token: str | None) -> Person | None:
    """Who the session belongs to, while it lasts and they still have a sign-in."""
    if not token:
        return None
    with _connect(workspace_path) as conn:
        row = conn.execute(
            "SELECT person_id, expires_at FROM admin_sessions WHERE token_hash = ?", (_token_hash(token),)
        ).fetchone()
    if row is None or row[1] < utc_iso(datetime.now(UTC)):
        return None
    person = get_person(workspace_path, row[0])
    return person if person is not None and person.sign_in is not None else None


def end_session(workspace_path: Path, token: str | None) -> None:
    if not token:
        return
    with _connect(workspace_path) as conn:
        conn.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (_token_hash(token),))
        conn.commit()
