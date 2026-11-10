"""The family: people and their roles (the plan's Phase 6).

One list, owned by the core. A person has a name, what Hiro calls them, a WhatsApp
number, one role, and a sign-in only if they use the admin. Extensions (HomeHiro
first) read the list and are told when it changes; what a role may do inside an
extension stays with that extension. The core checks nothing per role in Phase 6:
whoever signs in to the admin can do everything there.

- ``roles`` and ``people`` are durable rows in workspace.db.
- Owner, Adult and Kid are there from the start (the same ids HomeHiro uses);
  Owner is built in and can't be renamed or removed.
- Passwords and sign-in sessions live in ``admin_sign_in.py``; this module only
  stores the hash it is given.

Every change publishes ``DomainEventType.PEOPLE_CHANGED`` on the domain event bus.
All functions are synchronous (CLI and admin worker threads).
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hiro_commons.timestamps import utc_iso
from pydantic import BaseModel

from .db import db_path, ensure_db
from .events import DomainEvent, DomainEventType, get_domain_event_bus

OWNER_ROLE = "owner"

# (role_id, name, built_in) — HomeHiro's role ids, so its rights per role keep their keys.
DEFAULT_ROLES: tuple[tuple[str, str, bool], ...] = (
    (OWNER_ROLE, "Owner", True),
    ("adult", "Adult", False),
    ("kid", "Kid", False),
)

NAME_MAX = 80
SIGN_IN_MAX = 40


class PeopleError(ValueError):
    """A change that can't be made as asked; the message says why, for people."""


class Role(BaseModel):
    role_id: str
    name: str
    built_in: bool = False
    # Phase 8: whether people with this role can open HiroLeague's settings (the admin). Owner always can;
    # the others sign in only for the apps (the dashboard's Apps card) until a role is switched on.
    admin: bool = False


class Person(BaseModel):
    person_id: str
    name: str
    calls_them: str = ""
    whatsapp: str = ""  # digits with the country code, "" = none
    role_id: str
    sign_in: str | None = None  # the admin sign-in name, None = doesn't use the admin
    created_at: str = ""
    updated_at: str = ""

    @property
    def hiro_calls_them(self) -> str:
        """What Hiro calls them: their own nickname, else their name."""
        return self.calls_them or self.name

    def public(self) -> dict[str, Any]:
        """The person as the admin, the CLI and extensions see them (no password hash here)."""
        return {**self.model_dump(), "has_sign_in": self.sign_in is not None}


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------


def _now() -> str:
    return utc_iso(datetime.now(UTC))


def _connect(workspace_path: Path) -> sqlite3.Connection:
    ensure_db(workspace_path)
    conn = sqlite3.connect(str(db_path(workspace_path)))
    conn.row_factory = sqlite3.Row
    _seed_roles(conn)
    return conn


def _seed_roles(conn: sqlite3.Connection) -> None:
    """Owner, Adult and Kid on a workspace that has no roles yet."""
    if conn.execute("SELECT 1 FROM roles LIMIT 1").fetchone() is not None:
        return
    conn.executemany(
        "INSERT INTO roles (role_id, name, built_in, position, admin) VALUES (?, ?, ?, ?, ?)",
        [
            (rid, name, int(built_in), pos, int(rid == OWNER_ROLE))
            for pos, (rid, name, built_in) in enumerate(DEFAULT_ROLES)
        ],
    )
    conn.commit()


def _changed(workspace_path: Path, what: str, **payload: Any) -> None:
    get_domain_event_bus().publish(
        DomainEvent(type=DomainEventType.PEOPLE_CHANGED, workspace_path=workspace_path, payload={"what": what, **payload})
    )


def _clean_name(value: str, what: str = "Name") -> str:
    name = " ".join((value or "").split())
    if not name:
        raise PeopleError(f"{what} is empty.")
    if len(name) > NAME_MAX:
        raise PeopleError(f"{what} is longer than {NAME_MAX} characters.")
    return name


def clean_number(value: str) -> str:
    """A WhatsApp number as stored: its digits, with the country code ("" = none)."""
    number = re.sub(r"\D", "", value or "")
    if number and not 8 <= len(number) <= 15:
        raise PeopleError("The WhatsApp number needs the country code, e.g. +20 100 123 4567.")
    return number


def _clean_sign_in(value: str) -> str:
    sign_in = (value or "").strip()
    if not sign_in:
        raise PeopleError("The sign-in name is empty.")
    if len(sign_in) > SIGN_IN_MAX or not re.fullmatch(r"[\w.@-]+", sign_in):
        raise PeopleError(
            f"A sign-in name is up to {SIGN_IN_MAX} letters, digits, dots, dashes or @, without spaces."
        )
    return sign_in


def _row_to_role(row: sqlite3.Row) -> Role:
    # Owner always opens the settings, whatever the column says (Phase 8).
    admin = row["role_id"] == OWNER_ROLE or bool(row["admin"])
    return Role(role_id=row["role_id"], name=row["name"], built_in=bool(row["built_in"]), admin=admin)


def _row_to_person(row: sqlite3.Row) -> Person:
    return Person(
        person_id=row["person_id"],
        name=row["name"],
        calls_them=row["calls_them"] or "",
        whatsapp=row["whatsapp"] or "",
        role_id=row["role_id"],
        sign_in=row["sign_in"],
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


def list_roles(workspace_path: Path) -> list[Role]:
    with _connect(workspace_path) as conn:
        rows = conn.execute("SELECT * FROM roles ORDER BY position, name").fetchall()
    return [_row_to_role(r) for r in rows]


def get_role(workspace_path: Path, role_id: str) -> Role | None:
    with _connect(workspace_path) as conn:
        row = conn.execute("SELECT * FROM roles WHERE role_id = ?", (role_id,)).fetchone()
    return _row_to_role(row) if row else None


def _role_id_from(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "role"
    role_id, n = base, 2
    while role_id in taken:
        role_id, n = f"{base}-{n}", n + 1
    return role_id


def add_role(workspace_path: Path, name: str) -> Role:
    name = _clean_name(name, "The role's name")
    with _connect(workspace_path) as conn:
        rows = conn.execute("SELECT role_id, name, position FROM roles").fetchall()
        if any(r["name"].lower() == name.lower() for r in rows):
            raise PeopleError(f"There is already a role called {name}.")
        role = Role(role_id=_role_id_from(name, {r["role_id"] for r in rows}), name=name)
        position = max((r["position"] for r in rows), default=-1) + 1
        conn.execute(
            "INSERT INTO roles (role_id, name, built_in, position) VALUES (?, ?, 0, ?)",
            (role.role_id, role.name, position),
        )
        conn.commit()
    _changed(workspace_path, "role_added", role_id=role.role_id)
    return role


def rename_role(workspace_path: Path, role_id: str, name: str) -> Role:
    name = _clean_name(name, "The role's name")
    role = get_role(workspace_path, role_id)
    if role is None:
        raise PeopleError("That role doesn't exist.")
    if role.built_in:
        raise PeopleError(f"{role.name} is built in and keeps its name.")
    with _connect(workspace_path) as conn:
        clash = conn.execute(
            "SELECT 1 FROM roles WHERE lower(name) = lower(?) AND role_id != ?", (name, role_id)
        ).fetchone()
        if clash:
            raise PeopleError(f"There is already a role called {name}.")
        conn.execute("UPDATE roles SET name = ? WHERE role_id = ?", (name, role_id))
        conn.commit()
    _changed(workspace_path, "role_renamed", role_id=role_id)
    return role.model_copy(update={"name": name})


def set_role_admin(workspace_path: Path, role_id: str, admin: bool) -> Role:
    """Phase 8: switch whether a role can open HiroLeague's settings (not Owner's, which always can)."""
    role = get_role(workspace_path, role_id)
    if role is None:
        raise PeopleError("That role doesn't exist.")
    if role.role_id == OWNER_ROLE:
        raise PeopleError("The owner always opens HiroLeague's settings.")
    with _connect(workspace_path) as conn:
        conn.execute("UPDATE roles SET admin = ? WHERE role_id = ?", (int(bool(admin)), role_id))
        conn.commit()
    _changed(workspace_path, "role_admin", role_id=role_id)
    return role.model_copy(update={"admin": bool(admin)})


def role_opens_settings(workspace_path: Path, role_id: str) -> bool:
    """Whether people with this role can open HiroLeague's settings (Phase 8); an unknown role can't."""
    role = get_role(workspace_path, role_id)
    return role is not None and role.admin


def remove_role(workspace_path: Path, role_id: str) -> None:
    role = get_role(workspace_path, role_id)
    if role is None:
        raise PeopleError("That role doesn't exist.")
    if role.built_in:
        raise PeopleError(f"{role.name} is built in and can't be removed.")
    with _connect(workspace_path) as conn:
        users = [r["name"] for r in conn.execute("SELECT name FROM people WHERE role_id = ?", (role_id,))]
        if users:
            raise PeopleError(f"{role.name} is still given to {', '.join(users)}; give them another role first.")
        conn.execute("DELETE FROM roles WHERE role_id = ?", (role_id,))
        conn.commit()
    _changed(workspace_path, "role_removed", role_id=role_id)


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------


def list_people(workspace_path: Path) -> list[Person]:
    """Everyone, by role (Owner first) then name."""
    with _connect(workspace_path) as conn:
        rows = conn.execute(
            "SELECT p.* FROM people p LEFT JOIN roles r ON r.role_id = p.role_id "
            "ORDER BY COALESCE(r.position, 999), lower(p.name)"
        ).fetchall()
    return [_row_to_person(r) for r in rows]


def get_person(workspace_path: Path, person_id: str) -> Person | None:
    with _connect(workspace_path) as conn:
        row = conn.execute("SELECT * FROM people WHERE person_id = ?", (person_id,)).fetchone()
    return _row_to_person(row) if row else None


def _check_role(conn: sqlite3.Connection, role_id: str) -> None:
    if conn.execute("SELECT 1 FROM roles WHERE role_id = ?", (role_id,)).fetchone() is None:
        raise PeopleError(f"There is no role {role_id!r}.")


def _check_number_free(conn: sqlite3.Connection, number: str, person_id: str | None) -> None:
    if not number:
        return
    row = conn.execute(
        "SELECT name FROM people WHERE whatsapp = ? AND person_id != ?", (number, person_id or "")
    ).fetchone()
    if row:
        raise PeopleError(f"{row['name']} already has that WhatsApp number.")


def add_person(
    workspace_path: Path,
    *,
    name: str,
    role_id: str,
    calls_them: str = "",
    whatsapp: str = "",
) -> Person:
    name = _clean_name(name)
    calls_them = " ".join((calls_them or "").split())
    number = clean_number(whatsapp)
    now = _now()
    person = Person(
        person_id=uuid.uuid4().hex,
        name=name,
        calls_them=calls_them,
        whatsapp=number,
        role_id=role_id,
        created_at=now,
        updated_at=now,
    )
    with _connect(workspace_path) as conn:
        _check_role(conn, role_id)
        _check_number_free(conn, number, None)
        conn.execute(
            "INSERT INTO people (person_id, name, calls_them, whatsapp, role_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (person.person_id, person.name, person.calls_them, person.whatsapp, person.role_id, now, now),
        )
        conn.commit()
    _changed(workspace_path, "person_added", person_id=person.person_id)
    return person


def update_person(
    workspace_path: Path,
    person_id: str,
    *,
    name: str | None = None,
    role_id: str | None = None,
    calls_them: str | None = None,
    whatsapp: str | None = None,
) -> Person:
    """Change what is given (None = leave as it is)."""
    person = get_person(workspace_path, person_id)
    if person is None:
        raise PeopleError("That person isn't in the family list.")
    changes: dict[str, Any] = {}
    if name is not None:
        changes["name"] = _clean_name(name)
    if calls_them is not None:
        changes["calls_them"] = " ".join(calls_them.split())
    if whatsapp is not None:
        changes["whatsapp"] = clean_number(whatsapp)
    if role_id is not None:
        changes["role_id"] = role_id
    if not changes:
        return person
    with _connect(workspace_path) as conn:
        if "role_id" in changes:
            _check_role(conn, changes["role_id"])
            if person.role_id == OWNER_ROLE and changes["role_id"] != OWNER_ROLE:
                _check_not_last_owner(conn, person)
        if "whatsapp" in changes:
            _check_number_free(conn, changes["whatsapp"], person_id)
        changes["updated_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in changes)
        conn.execute(f"UPDATE people SET {cols} WHERE person_id = ?", (*changes.values(), person_id))
        conn.commit()
    _changed(workspace_path, "person_updated", person_id=person_id)
    return person.model_copy(update=changes)


def _check_not_last_owner(conn: sqlite3.Connection, person: Person) -> None:
    owners = conn.execute("SELECT COUNT(*) FROM people WHERE role_id = ?", (OWNER_ROLE,)).fetchone()[0]
    if owners <= 1:
        raise PeopleError(f"{person.name} is the only Owner; make someone else Owner first.")


def _check_not_last_sign_in(conn: sqlite3.Connection, person: Person) -> None:
    others = conn.execute(
        "SELECT COUNT(*) FROM people WHERE sign_in IS NOT NULL AND person_id != ?", (person.person_id,)
    ).fetchone()[0]
    if others == 0:
        raise PeopleError(f"{person.name} is the only one who can sign in to the admin; keep their sign-in.")


def remove_person(workspace_path: Path, person_id: str) -> Person:
    person = get_person(workspace_path, person_id)
    if person is None:
        raise PeopleError("That person isn't in the family list.")
    with _connect(workspace_path) as conn:
        if person.role_id == OWNER_ROLE:
            _check_not_last_owner(conn, person)
        if person.sign_in is not None:
            _check_not_last_sign_in(conn, person)
        conn.execute("DELETE FROM admin_sessions WHERE person_id = ?", (person_id,))
        conn.execute("DELETE FROM people WHERE person_id = ?", (person_id,))
        conn.commit()
    _changed(workspace_path, "person_removed", person_id=person_id)
    return person


def find_by_number(workspace_path: Path, number: str) -> Person | None:
    number = re.sub(r"\D", "", number or "")
    if not number:
        return None
    with _connect(workspace_path) as conn:
        row = conn.execute("SELECT * FROM people WHERE whatsapp = ?", (number,)).fetchone()
    return _row_to_person(row) if row else None


# ---------------------------------------------------------------------------
# Admin sign-in: names and stored hashes (the hashing is admin_sign_in.py's)
# ---------------------------------------------------------------------------


def set_sign_in(workspace_path: Path, person_id: str, *, sign_in: str, password_hash: str) -> Person:
    """Give a person a sign-in, or change its name or password; ends their other sessions."""
    sign_in = _clean_sign_in(sign_in)
    person = get_person(workspace_path, person_id)
    if person is None:
        raise PeopleError("That person isn't in the family list.")
    with _connect(workspace_path) as conn:
        clash = conn.execute(
            "SELECT name FROM people WHERE lower(sign_in) = lower(?) AND person_id != ?", (sign_in, person_id)
        ).fetchone()
        if clash:
            raise PeopleError(f"{clash['name']} already signs in as {sign_in}.")
        conn.execute(
            "UPDATE people SET sign_in = ?, password_hash = ?, updated_at = ? WHERE person_id = ?",
            (sign_in, password_hash, _now(), person_id),
        )
        conn.execute("DELETE FROM admin_sessions WHERE person_id = ?", (person_id,))
        conn.commit()
    _changed(workspace_path, "sign_in_set", person_id=person_id)
    return person.model_copy(update={"sign_in": sign_in})


def clear_sign_in(workspace_path: Path, person_id: str) -> Person:
    """Take a person's admin sign-in away (never the last one)."""
    person = get_person(workspace_path, person_id)
    if person is None:
        raise PeopleError("That person isn't in the family list.")
    if person.sign_in is None:
        return person
    with _connect(workspace_path) as conn:
        _check_not_last_sign_in(conn, person)
        conn.execute(
            "UPDATE people SET sign_in = NULL, password_hash = NULL, updated_at = ? WHERE person_id = ?",
            (_now(), person_id),
        )
        conn.execute("DELETE FROM admin_sessions WHERE person_id = ?", (person_id,))
        conn.commit()
    _changed(workspace_path, "sign_in_cleared", person_id=person_id)
    return person.model_copy(update={"sign_in": None})


def sign_in_hash(workspace_path: Path, sign_in: str) -> tuple[Person, str] | None:
    """The person who signs in with that name (any case) and their stored password hash."""
    with _connect(workspace_path) as conn:
        row = conn.execute(
            "SELECT * FROM people WHERE lower(sign_in) = lower(?) AND password_hash IS NOT NULL",
            ((sign_in or "").strip(),),
        ).fetchone()
    return (_row_to_person(row), row["password_hash"]) if row else None


def anyone_signs_in(workspace_path: Path) -> bool:
    """True once at least one person can sign in to the admin."""
    with _connect(workspace_path) as conn:
        return conn.execute("SELECT 1 FROM people WHERE sign_in IS NOT NULL LIMIT 1").fetchone() is not None
