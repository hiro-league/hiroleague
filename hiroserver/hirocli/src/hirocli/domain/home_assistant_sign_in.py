"""'Sign in with Home Assistant', run by the core: an option the owner adds on People → Sign-in (trust fixes, Nov 25).

The core keeps its own connection to Home Assistant (an address; the access token in the OS keyring, as provider keys
are) and who each Home Assistant login is in the family list. The sign-in page shows the button only while the owner
has it on and the last connection test worked. No app takes part: before this, an app offered the sign-in and the
core believed whoever it said had signed in.

The login itself, the connection test and the people list are the client's (services/home_assistant.py); the routes
are admin_svelte/routes/sign_in_ways.py (the owner's) and routes/auth.py (the sign-in page's).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import keyring_secrets
from .db import db_path, ensure_db
from .people import list_people
from .workspace import workspace_id_for_path

TOKEN_USER = "token"


class HaSignInError(Exception):
    """An expected "no", in words for the owner."""


@dataclass(frozen=True)
class HaLogin:
    """A Home Assistant person with a login, and who they are in the family list ('' = nobody: they can't sign in)."""

    ha_user_id: str
    name: str
    login: str
    person_id: str = ""


@dataclass(frozen=True)
class HaSignIn:
    address: str
    enabled: bool
    version: str  # Home Assistant's version at the last good test; '' = not connected
    checked_at: str
    token_set: bool

    @property
    def connected(self) -> bool:
        return bool(self.address and self.version and self.token_set)

    @property
    def offered(self) -> bool:
        """The sign-in page shows the button: the owner has it on, and the core reaches Home Assistant."""
        return self.enabled and self.connected


def _service(workspace_path: Path) -> str:
    wid = workspace_id_for_path(workspace_path) or f"path:{workspace_path.resolve()}"
    return f"hiroleague:{wid}:home_assistant"


def token(workspace_path: Path) -> str | None:
    return keyring_secrets.get_secret(_service(workspace_path), TOKEN_USER)


def _connect(workspace_path: Path) -> sqlite3.Connection:
    ensure_db(workspace_path)
    return sqlite3.connect(str(db_path(workspace_path)))


def read(workspace_path: Path) -> HaSignIn:
    with _connect(workspace_path) as conn:
        row = conn.execute("SELECT address, enabled, version, checked_at FROM ha_sign_in WHERE id = 1").fetchone()
    address, enabled, version, checked_at = row or ("", 0, "", "")
    return HaSignIn(address, bool(enabled), version, checked_at, token_set=bool(token(workspace_path)))


def logins(workspace_path: Path) -> list[HaLogin]:
    with _connect(workspace_path) as conn:
        rows = conn.execute("SELECT ha_user_id, name, login, person_id FROM ha_logins ORDER BY name COLLATE NOCASE").fetchall()
    return [HaLogin(*r) for r in rows]


def suggested(found: list[HaLogin], kept: dict[str, str], family: dict[str, str]) -> list[HaLogin]:
    """Who each login found is: kept as the owner linked it; a new one suggested as the one family person of the same
    name (case aside), else nobody. `kept` = ha_user_id → person_id; `family` = person_id → name."""
    by_name: dict[str, list[str]] = {}
    for person_id, name in family.items():
        by_name.setdefault(name.strip().lower(), []).append(person_id)
    out = []
    for login in found:
        if login.ha_user_id in kept:
            person_id = kept[login.ha_user_id]
        else:
            same = by_name.get(login.name.strip().lower(), [])
            person_id = same[0] if len(same) == 1 else ""
        out.append(HaLogin(login.ha_user_id, login.name, login.login, person_id))
    return out


def connected(workspace_path: Path, address: str, access_token: str, version: str, found: list[HaLogin]) -> HaSignIn:
    """A connection test worked: keep the address, the token and who is who (the logins Home Assistant has now)."""
    try:
        keyring_secrets.set_secret(_service(workspace_path), TOKEN_USER, access_token)
    except Exception as exc:  # the keyring's own errors vary by backend; said in words, never the token
        raise HaSignInError("The access token couldn't be kept in this computer's keyring.") from exc
    kept = {lg.ha_user_id: lg.person_id for lg in logins(workspace_path)}
    family = {p.person_id: p.name for p in list_people(workspace_path)}
    now = datetime.now(UTC).isoformat()
    with _connect(workspace_path) as conn:
        conn.execute(
            "INSERT INTO ha_sign_in (id, address, version, checked_at) VALUES (1, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET address = excluded.address, version = excluded.version, "
            "checked_at = excluded.checked_at",
            (address, version, now),
        )
        conn.execute("DELETE FROM ha_logins")
        conn.executemany(
            "INSERT INTO ha_logins (ha_user_id, name, login, person_id) VALUES (?, ?, ?, ?)",
            [(lg.ha_user_id, lg.name, lg.login, lg.person_id) for lg in suggested(found, kept, family)],
        )
    return read(workspace_path)


def disconnect(workspace_path: Path) -> HaSignIn:
    """The owner disconnects: the token goes, the button goes; who is who stays for a later connection."""
    keyring_secrets.delete_secret(_service(workspace_path), TOKEN_USER)
    with _connect(workspace_path) as conn:
        conn.execute("UPDATE ha_sign_in SET address = '', enabled = 0, version = '', checked_at = '' WHERE id = 1")
    return read(workspace_path)


def set_enabled(workspace_path: Path, on: bool) -> HaSignIn:
    if on and not read(workspace_path).connected:
        raise HaSignInError("Connect Home Assistant first: the sign-in needs it.")
    with _connect(workspace_path) as conn:
        conn.execute("UPDATE ha_sign_in SET enabled = ? WHERE id = 1", (int(on),))
    return read(workspace_path)


def link(workspace_path: Path, ha_user_id: str, person_id: str) -> HaLogin:
    """Who a Home Assistant login is in the family list ('' = nobody)."""
    if person_id and person_id not in {p.person_id for p in list_people(workspace_path)}:
        raise HaSignInError("That person isn't in the family list.")
    with _connect(workspace_path) as conn:
        changed = conn.execute("UPDATE ha_logins SET person_id = ? WHERE ha_user_id = ?", (person_id, ha_user_id))
        if not changed.rowcount:
            raise HaSignInError("That Home Assistant login isn't known: test the connection again.")
    return next(lg for lg in logins(workspace_path) if lg.ha_user_id == ha_user_id)


def person_of(workspace_path: Path, ha_user_id: str) -> str:
    """The family person a Home Assistant login signs in as; '' = nobody."""
    with _connect(workspace_path) as conn:
        row = conn.execute("SELECT person_id FROM ha_logins WHERE ha_user_id = ?", (ha_user_id,)).fetchone()
    return row[0] if row else ""
