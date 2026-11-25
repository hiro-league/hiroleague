"""'Sign in with Home Assistant', run by the core: an option the owner adds on People → Sign-in (trust fixes, Nov 25).

The core keeps its own connection to Home Assistant and who each Home Assistant login is in the family list. The
sign-in page shows the button only while the owner has it on and the last connection test worked. No app takes part:
before this, an app offered the sign-in and the core believed whoever it said had signed in.

- **Two addresses,** as HomeHiro keeps them: where the core reaches HA (Simone reaches it by its IP, http://192.168.1.11)
  and where people's browsers go to log in (http://homeassistant.local); the second is the first when left empty.
- **The access token** is kept in `ha_sign_in` and never answered or logged, as an app keeps its HA token: the live
  core's keyring is locked without a login session. The table is per place (data.toml): a copy never brings live's.
- **Who is who:** a login the owner linked signs in as that person; one linked to nobody can't sign in. A new login is
  suggested as the one family person of the same name, and the suggestion signs nobody in until the owner links it.

The login itself, the connection test and the people list are the client's (services/home_assistant.py); the routes
are admin_svelte/routes/sign_in_ways.py (the owner's) and routes/auth.py (the sign-in page's).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .db import db_path, ensure_db
from .people import list_people


class HaSignInError(Exception):
    """An expected "no", in words for the owner."""


@dataclass(frozen=True)
class HaLogin:
    """A Home Assistant person with a login; who the owner linked it to ('' = nobody: it can't sign in) and who it is
    suggested to be by name (a suggestion only)."""

    ha_user_id: str
    name: str
    login: str
    person_id: str = ""
    suggested_id: str = ""


@dataclass(frozen=True)
class HaSignIn:
    address: str  # where the core reaches HA
    link_address: str  # where people's browsers log in; '' = `address`
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

    @property
    def browser_address(self) -> str:
        return self.link_address or self.address


def _connect(workspace_path: Path) -> sqlite3.Connection:
    ensure_db(workspace_path)
    return sqlite3.connect(str(db_path(workspace_path)))


def read(workspace_path: Path) -> HaSignIn:
    with _connect(workspace_path) as conn:
        row = conn.execute(
            "SELECT address, link_address, token != '', enabled, version, checked_at FROM ha_sign_in WHERE id = 1"
        ).fetchone()
    address, link_address, token_set, enabled, version, checked_at = row or ("", "", 0, 0, "", "")
    return HaSignIn(address, link_address, bool(enabled), version, checked_at, token_set=bool(token_set))


def token(workspace_path: Path) -> str:
    """The access token kept ('' = none). Never answered or logged."""
    with _connect(workspace_path) as conn:
        row = conn.execute("SELECT token FROM ha_sign_in WHERE id = 1").fetchone()
    return row[0] if row else ""


def logins(workspace_path: Path) -> list[HaLogin]:
    with _connect(workspace_path) as conn:
        rows = conn.execute(
            "SELECT ha_user_id, name, login, person_id, suggested_id FROM ha_logins ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return [HaLogin(*r) for r in rows]


def suggested(found: list[HaLogin], kept: dict[str, str], family: dict[str, str]) -> list[HaLogin]:
    """Who each login found is: linked as the owner linked it (`kept`: ha_user_id → person_id), and suggested as the
    one family person of the same name, case aside (`family`: person_id → name). A suggestion links nobody."""
    by_name: dict[str, list[str]] = {}
    for person_id, name in family.items():
        by_name.setdefault(name.strip().lower(), []).append(person_id)
    out = []
    for login in found:
        same = by_name.get(login.name.strip().lower(), [])
        out.append(HaLogin(login.ha_user_id, login.name, login.login, person_id=kept.get(login.ha_user_id, ""),
                           suggested_id=same[0] if len(same) == 1 else ""))
    return out


def connected(workspace_path: Path, address: str, link_address: str, access_token: str, version: str,
              found: list[HaLogin]) -> HaSignIn:
    """A connection test worked: keep the addresses, the token and who is who (the logins Home Assistant has now)."""
    family = {p.person_id: p.name for p in list_people(workspace_path)}
    kept = {lg.ha_user_id: lg.person_id for lg in logins(workspace_path) if lg.person_id in family}
    now = datetime.now(UTC).isoformat()
    with _connect(workspace_path) as conn:
        conn.execute(
            "INSERT INTO ha_sign_in (id, address, link_address, token, version, checked_at) VALUES (1, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET address = excluded.address, link_address = excluded.link_address, "
            "token = excluded.token, version = excluded.version, checked_at = excluded.checked_at",
            (address, link_address, access_token, version, now),
        )
        conn.execute("DELETE FROM ha_logins")
        conn.executemany(
            "INSERT INTO ha_logins (ha_user_id, name, login, person_id, suggested_id) VALUES (?, ?, ?, ?, ?)",
            [(lg.ha_user_id, lg.name, lg.login, lg.person_id, lg.suggested_id)
             for lg in suggested(found, kept, family)],
        )
    return read(workspace_path)


def disconnect(workspace_path: Path) -> HaSignIn:
    """The owner disconnects: the token and the button go; who is who stays for a later connection."""
    with _connect(workspace_path) as conn:
        conn.execute(
            "UPDATE ha_sign_in SET address = '', link_address = '', token = '', enabled = 0, version = '', "
            "checked_at = '' WHERE id = 1"
        )
    return read(workspace_path)


def set_enabled(workspace_path: Path, on: bool) -> HaSignIn:
    if on and not read(workspace_path).connected:
        raise HaSignInError("Connect Home Assistant first: the sign-in needs it.")
    with _connect(workspace_path) as conn:
        conn.execute("UPDATE ha_sign_in SET enabled = ? WHERE id = 1", (int(on),))
    return read(workspace_path)


def link(workspace_path: Path, ha_user_id: str, person_id: str) -> HaLogin:
    """The owner says who a Home Assistant login is in the family list ('' = nobody)."""
    if person_id and person_id not in {p.person_id for p in list_people(workspace_path)}:
        raise HaSignInError("That person isn't in the family list.")
    with _connect(workspace_path) as conn:
        changed = conn.execute("UPDATE ha_logins SET person_id = ? WHERE ha_user_id = ?", (person_id, ha_user_id))
        if not changed.rowcount:
            raise HaSignInError("That Home Assistant login isn't known: test the connection again.")
    return next(lg for lg in logins(workspace_path) if lg.ha_user_id == ha_user_id)


def person_of(workspace_path: Path, ha_user_id: str) -> str:
    """The family person a Home Assistant login signs in as, as the owner linked it; '' = nobody."""
    with _connect(workspace_path) as conn:
        row = conn.execute("SELECT person_id FROM ha_logins WHERE ha_user_id = ?", (ha_user_id,)).fetchone()
    return row[0] if row else ""
