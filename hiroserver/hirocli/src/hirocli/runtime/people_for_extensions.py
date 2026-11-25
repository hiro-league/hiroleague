"""The family list for extensions (the plan's Phase 6).

HomeHiro reads the core's people and roles (``people.list``), adds or changes them
when its admin does that in HomeHiro (``people.add``, ``people.update``, ``roles.*``),
and is told to read again when anything changes (``resource.changed`` for ``people``, sent to
every connected app by the one sender, resource_change_broadcaster.py). Contract: hiro_channel_sdk.constants.

The operations are the family list's own (domain/people.py, the same ones the people
tools call), run in a worker thread so the event loop never waits on SQLite.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hiro_channel_sdk.constants import (
    METHOD_PEOPLE_ADD,
    METHOD_PEOPLE_LIST,
    METHOD_PEOPLE_UPDATE,
    METHOD_ROLES_ADD,
    METHOD_ROLES_IMPORT_RIGHTS,
    METHOD_ROLES_REMOVE,
    METHOD_ROLES_RENAME,
)
from hiro_commons.log import Logger

from ..domain.access import copy_rights, import_rights, rename_rights, roles_for_extension
from ..domain.people import (
    OWNER_ROLE,
    PeopleError,
    Person,
    add_person,
    add_role,
    get_person,
    list_people,
    remove_role,
    rename_role,
    update_person,
)
from .ai_for_extensions import _caller_name
from .request_handler import EXTENSIONS_ONLY, RequestContext, RequestRefused
from .whatsapp_for_extensions import sender_label

log = Logger.get("PEOPLE")


def for_extension(person: Person | dict[str, Any]) -> dict[str, Any]:
    """A person as extensions see them: no admin sign-in details."""
    data = person.model_dump() if isinstance(person, Person) else dict(person)
    return {
        **{k: data.get(k, "") for k in ("person_id", "name", "calls_them", "whatsapp", "role_id")},
        "role_ids": list(data.get("role_ids") or []),  # every role they hold; role_id is the first (phase 1)
    }


def _workspace(ctx: RequestContext) -> Path:
    return Path(ctx.server_ctx.workspace_path)


async def _change(ctx: RequestContext, what: str, run: Callable[[], Any]) -> Any:
    try:
        result = await asyncio.to_thread(run)
    except PeopleError as exc:
        raise RequestRefused("invalid_params", str(exc)) from exc
    log.info(f"⬇️ People changed — {what} · by {sender_label(ctx)}")
    return result


async def handle_people_list(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    del params
    workspace_path = _workspace(ctx)
    people = await asyncio.to_thread(list_people, workspace_path)
    # Phase 9a: each role carries its line and the rights it has in the calling extension (not the others').
    roles = await asyncio.to_thread(roles_for_extension, workspace_path, await _caller_name(ctx))
    log.fineinfo(f"⬆️ People list served — {sender_label(ctx)}", count=len(people))
    return {"people": [for_extension(p) for p in people], "roles": roles}


def _str(params: dict[str, Any], key: str) -> str | None:
    """A text field as given, None when left out (people.update leaves it as it is)."""
    value = params.get(key)
    return None if value is None else str(value)


def _role_ids(params: dict[str, Any]) -> list[str] | None:
    """Every role a person is to hold (``role_ids``), None when left out; a value that isn't a list is refused."""
    value = params.get("role_ids")
    if value is None:
        return None
    if not isinstance(value, list):
        raise RequestRefused("invalid_params", "role_ids must be a list of role ids")
    return [str(r) for r in value]


_NO_OWNER = "No app gives or takes the Owner role: that is done in HiroLeague's admin."


def _gives_or_takes_owner(workspace_path: Path, person_id: str, role_id: str | None, role_ids: list[str] | None) -> bool:
    """Permissions phase 8: whether a change through an app would give or take the Owner role (it never may, whoever
    is signed in). One ``role_id`` alone makes it their only role."""
    new = role_ids if role_ids is not None else ([role_id] if role_id else None)
    if new is None:
        return False
    old = get_person(workspace_path, person_id) if person_id else None
    return (OWNER_ROLE in new) != (old is not None and OWNER_ROLE in old.role_ids)


async def handle_people_add(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    role_ids = _role_ids(params)
    if await asyncio.to_thread(_gives_or_takes_owner, _workspace(ctx), "", _str(params, "role_id"), role_ids):
        raise RequestRefused("not_allowed", _NO_OWNER)
    person = await _change(
        ctx,
        "person added",
        lambda: add_person(
            _workspace(ctx),
            name=_str(params, "name") or "",
            role_id=_str(params, "role_id") or "",
            role_ids=role_ids,
            calls_them=_str(params, "calls_them") or "",
            whatsapp=_str(params, "whatsapp") or "",
        ),
    )
    return {"person": for_extension(person)}


async def handle_people_update(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    person_id = _str(params, "person_id")
    if not person_id:
        raise RequestRefused("invalid_params", "person_id is missing")
    role_ids = _role_ids(params)
    if await asyncio.to_thread(_gives_or_takes_owner, _workspace(ctx), person_id, _str(params, "role_id"), role_ids):
        raise RequestRefused("not_allowed", _NO_OWNER)
    person = await _change(
        ctx,
        "person updated",
        lambda: update_person(
            _workspace(ctx),
            person_id,
            name=_str(params, "name"),
            role_id=_str(params, "role_id"),
            role_ids=role_ids,
            calls_them=_str(params, "calls_them"),
            whatsapp=_str(params, "whatsapp"),
        ),
    )
    return {"person": for_extension(person)}


async def handle_roles_add(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    role = await _change(ctx, "role added", lambda: add_role(_workspace(ctx), _str(params, "name") or ""))
    return {"role": role.model_dump()}


async def handle_roles_rename(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    role = await _change(
        ctx,
        "role renamed",
        lambda: rename_role(_workspace(ctx), _str(params, "role_id") or "", _str(params, "name") or ""),
    )
    return {"role": role.model_dump()}


async def handle_roles_remove(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    await _change(ctx, "role removed", lambda: remove_role(_workspace(ctx), _str(params, "role_id") or ""))
    return {}


async def handle_roles_import_rights(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    """Phase 9a: once, the extension's own grants from before; fills only roles with none there yet."""
    name = await _caller_name(ctx)
    copy_from = str(params.get("copy_from") or "").strip()
    if copy_from:
        # Phase 9b: an app taking features over from another copies each role's rights in them, once.
        filled = await _change(ctx, f"rights copied for {name} from {copy_from}",
                               lambda: copy_rights(_workspace(ctx), name, copy_from))
        return {"imported": filled}
    renamed = params.get("renamed")
    if renamed is not None:
        # Permissions phase 6: an app renamed some of its permissions; each role holding an old key gets the new ones.
        if not isinstance(renamed, dict) or not all(
                isinstance(k, str) and isinstance(v, list) and all(isinstance(x, str) for x in v) for k, v in renamed.items()):
            raise RequestRefused("invalid_params", "renamed must be {old key: [new keys]}")
        filled = await _change(ctx, f"rights renamed for {name}", lambda: rename_rights(_workspace(ctx), name, renamed))
        return {"imported": filled}
    roles = params.get("roles")
    if not isinstance(roles, dict):
        raise RequestRefused("invalid_params", "roles must be {role_id: {rights: [...], says?: str}}, or copy_from, or renamed")
    filled = await _change(ctx, f"rights imported for {name}", lambda: import_rights(_workspace(ctx), name, roles))
    return {"imported": filled}


# (method, handler, who may call it) — merged into request_methods' table.
PEOPLE_REQUEST_HANDLERS: tuple[tuple[str, Any, frozenset[str]], ...] = (
    (METHOD_PEOPLE_LIST, handle_people_list, EXTENSIONS_ONLY),
    (METHOD_PEOPLE_ADD, handle_people_add, EXTENSIONS_ONLY),
    (METHOD_PEOPLE_UPDATE, handle_people_update, EXTENSIONS_ONLY),
    (METHOD_ROLES_ADD, handle_roles_add, EXTENSIONS_ONLY),
    (METHOD_ROLES_RENAME, handle_roles_rename, EXTENSIONS_ONLY),
    (METHOD_ROLES_REMOVE, handle_roles_remove, EXTENSIONS_ONLY),
    (METHOD_ROLES_IMPORT_RIGHTS, handle_roles_import_rights, EXTENSIONS_ONLY),
)

