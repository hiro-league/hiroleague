"""People tools — the family list, its roles, and admin sign-ins (the plan's Phase 6).

One operation each, for every caller: the CLI (commands/people.py), the admin
(admin_svelte/routes/people.py), and the agent (``people_list`` only: Hiro can read
who the family is, never change it). The data lives in domain/people.py; passwords
in domain/admin_sign_in.py. A refused change raises ``PeopleError`` with a message
for people.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.admin_sign_in import give_sign_in
from ..domain.people import (
    OWNER_ROLE,
    PeopleError,
    add_person,
    add_role,
    clear_sign_in,
    get_person,
    list_people,
    list_roles,
    remove_person,
    remove_role,
    rename_role,
    update_person,
)
from ..domain.workspace import resolve_workspace
from .base import Tool, ToolParam

_WORKSPACE = ToolParam(str, "Workspace name (default: registry default)", required=False)


def _resolve_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


def find_person(workspace_path: Path, who: str) -> str:
    """A person's id from their id, name or sign-in name (any case)."""
    wanted = (who or "").strip().lower()
    people = list_people(workspace_path)
    for p in people:
        if p.person_id == who:
            return p.person_id
    matches = [p for p in people if wanted in {p.name.lower(), (p.sign_in or "").lower()}]
    if len(matches) == 1:
        return matches[0].person_id
    if matches:
        raise PeopleError(f"More than one person is called {who}; use their id (hiro people list).")
    raise PeopleError(f"Nobody called {who} is in the family list.")


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class PeopleListResult:
    people: list[dict[str, Any]] = field(default_factory=list)
    roles: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PersonResult:
    person: dict[str, Any]


@dataclass
class RoleResult:
    role: dict[str, Any]


@dataclass
class RemovedResult:
    removed: str


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


class PeopleListTool(Tool):
    name = "people_list"
    description = (
        "List the family: each person's name, what Hiro calls them, their role (Owner, Adult, Kid…) "
        "and WhatsApp number; plus the roles"
    )
    params = {"workspace": _WORKSPACE}

    def execute(self, workspace: str | None = None) -> PeopleListResult:
        workspace_path = _resolve_path(workspace)
        return PeopleListResult(
            people=[p.public() for p in list_people(workspace_path)],
            roles=[r.model_dump() for r in list_roles(workspace_path)],
        )


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------


class PersonAddTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "person_add"
    description = "Add a person to the family list"
    params = {
        "name": ToolParam(str, "Their name"),
        "role_id": ToolParam(str, "Their role id (owner, adult, kid, …)"),
        "calls_them": ToolParam(str, "What Hiro calls them (default: their name)", required=False),
        "whatsapp": ToolParam(str, "WhatsApp number with the country code", required=False),
        "workspace": _WORKSPACE,
    }

    def execute(
        self,
        name: str,
        role_id: str,
        calls_them: str | None = None,
        whatsapp: str | None = None,
        workspace: str | None = None,
    ) -> PersonResult:
        person = add_person(
            _resolve_path(workspace), name=name, role_id=role_id, calls_them=calls_them or "", whatsapp=whatsapp or ""
        )
        return PersonResult(person=person.public())


class PersonUpdateTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "person_update"
    description = "Change a person's name, what Hiro calls them, role or WhatsApp number"
    params = {
        "person": ToolParam(str, "The person: id, name or sign-in name"),
        "name": ToolParam(str, "New name", required=False),
        "role_id": ToolParam(str, "New role id", required=False),
        "calls_them": ToolParam(str, "What Hiro calls them ('' = their name)", required=False),
        "whatsapp": ToolParam(str, "WhatsApp number with the country code ('' = none)", required=False),
        "workspace": _WORKSPACE,
    }

    def execute(
        self,
        person: str,
        name: str | None = None,
        role_id: str | None = None,
        calls_them: str | None = None,
        whatsapp: str | None = None,
        workspace: str | None = None,
    ) -> PersonResult:
        workspace_path = _resolve_path(workspace)
        updated = update_person(
            workspace_path,
            find_person(workspace_path, person),
            name=name,
            role_id=role_id,
            calls_them=calls_them,
            whatsapp=whatsapp,
        )
        return PersonResult(person=updated.public())


class PersonRemoveTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "person_remove"
    description = "Remove a person from the family list (never the only Owner or the only admin sign-in)"
    params = {"person": ToolParam(str, "The person: id, name or sign-in name"), "workspace": _WORKSPACE}

    def execute(self, person: str, workspace: str | None = None) -> RemovedResult:
        workspace_path = _resolve_path(workspace)
        removed = remove_person(workspace_path, find_person(workspace_path, person))
        return RemovedResult(removed=removed.person_id)


# ---------------------------------------------------------------------------
# Admin sign-in
# ---------------------------------------------------------------------------


class PersonSignInTool(Tool):
    # CLI only: not on the local /invoke API (no sign-in there); the admin calls it behind its own.
    surfaces = frozenset({"cli"})
    name = "person_sign_in"
    description = "Give a person an admin sign-in, or change its name or password (also resets a forgotten one)"
    params = {
        "person": ToolParam(str, "The person: id, name or sign-in name"),
        "sign_in": ToolParam(str, "The name they sign in with"),
        "password": ToolParam(str, "Their password (at least 8 characters)"),
        "workspace": _WORKSPACE,
    }

    def execute(self, person: str, sign_in: str, password: str, workspace: str | None = None) -> PersonResult:
        workspace_path = _resolve_path(workspace)
        updated = give_sign_in(workspace_path, find_person(workspace_path, person), sign_in=sign_in, password=password)
        return PersonResult(person=updated.public())


class PersonSignInRemoveTool(Tool):
    # CLI only: not on the local /invoke API (no sign-in there); the admin calls it behind its own.
    surfaces = frozenset({"cli"})
    name = "person_sign_in_remove"
    description = "Take a person's admin sign-in away (never the last one)"
    params = {"person": ToolParam(str, "The person: id, name or sign-in name"), "workspace": _WORKSPACE}

    def execute(self, person: str, workspace: str | None = None) -> PersonResult:
        workspace_path = _resolve_path(workspace)
        updated = clear_sign_in(workspace_path, find_person(workspace_path, person))
        return PersonResult(person=updated.public())


class OwnerSignInTool(Tool):
    """The owner's sign-in, from the machine itself (setup, or a forgotten password)."""

    surfaces = frozenset({"cli"})
    name = "people_owner"
    description = "Set the owner's admin sign-in: adds them as Owner when they aren't in the family list yet"
    params = {
        "name": ToolParam(str, "The owner's name"),
        "sign_in": ToolParam(str, "The name they sign in with"),
        "password": ToolParam(str, "Their password (at least 8 characters)"),
        "workspace": _WORKSPACE,
    }

    def execute(self, name: str, sign_in: str, password: str, workspace: str | None = None) -> PersonResult:
        workspace_path = _resolve_path(workspace)
        try:
            person_id = find_person(workspace_path, name)
        except PeopleError:
            person_id = add_person(workspace_path, name=name, role_id=OWNER_ROLE).person_id
        person = get_person(workspace_path, person_id)
        if person is not None and person.role_id != OWNER_ROLE:
            update_person(workspace_path, person_id, role_id=OWNER_ROLE)
        updated = give_sign_in(workspace_path, person_id, sign_in=sign_in, password=password)
        return PersonResult(person=updated.public())


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class RoleAddTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "role_add"
    description = "Add a role (what it may do inside an extension is set in that extension)"
    params = {"name": ToolParam(str, "The role's name"), "workspace": _WORKSPACE}

    def execute(self, name: str, workspace: str | None = None) -> RoleResult:
        return RoleResult(role=add_role(_resolve_path(workspace), name).model_dump())


class RoleRenameTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "role_rename"
    description = "Rename a role (not Owner)"
    params = {"role_id": ToolParam(str, "The role's id"), "name": ToolParam(str, "Its new name"), "workspace": _WORKSPACE}

    def execute(self, role_id: str, name: str, workspace: str | None = None) -> RoleResult:
        return RoleResult(role=rename_role(_resolve_path(workspace), role_id, name).model_dump())


class RoleRemoveTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "role_remove"
    description = "Remove a role nobody has (not Owner)"
    params = {"role_id": ToolParam(str, "The role's id"), "workspace": _WORKSPACE}

    def execute(self, role_id: str, workspace: str | None = None) -> RemovedResult:
        remove_role(_resolve_path(workspace), role_id)
        return RemovedResult(removed=role_id)
