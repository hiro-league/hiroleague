"""The family list for extensions (the plan's Phase 6).

HomeHiro reads the core's people and roles (``people.list``), adds or changes them
when its admin does that in HomeHiro (``people.add``, ``people.update``, ``roles.*``),
and is told to read again when anything changes (the ``people.changed`` event to every
connected extension). Contract: hiro_channel_sdk.constants.

The operations are the family list's own (domain/people.py, the same ones the people
tools call), run in a worker thread so the event loop never waits on SQLite.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hiro_channel_sdk.constants import (
    EVENT_PEOPLE_CHANGED,
    METHOD_PEOPLE_ADD,
    METHOD_PEOPLE_LIST,
    METHOD_PEOPLE_UPDATE,
    METHOD_ROLES_ADD,
    METHOD_ROLES_IMPORT_RIGHTS,
    METHOD_ROLES_REMOVE,
    METHOD_ROLES_RENAME,
)
from hiro_commons.log import Logger

from ..domain.access import import_rights, roles_for_extension
from ..domain.events import DomainEvent, DomainEventType, get_domain_event_bus
from ..domain.people import (
    PeopleError,
    Person,
    add_person,
    add_role,
    list_people,
    remove_role,
    rename_role,
    update_person,
)
from .ai_for_extensions import _caller_name
from .request_handler import EXTENSIONS_ONLY, RequestContext, RequestRefused
from .whatsapp_for_extensions import sender_label

if TYPE_CHECKING:
    from .extension_manager import ExtensionManager

log = Logger.get("PEOPLE")


def for_extension(person: Person | dict[str, Any]) -> dict[str, Any]:
    """A person as extensions see them: no admin sign-in details."""
    data = person.model_dump() if isinstance(person, Person) else dict(person)
    return {k: data.get(k, "") for k in ("person_id", "name", "calls_them", "whatsapp", "role_id")}


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


async def handle_people_add(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    person = await _change(
        ctx,
        "person added",
        lambda: add_person(
            _workspace(ctx),
            name=_str(params, "name") or "",
            role_id=_str(params, "role_id") or "",
            calls_them=_str(params, "calls_them") or "",
            whatsapp=_str(params, "whatsapp") or "",
        ),
    )
    return {"person": for_extension(person)}


async def handle_people_update(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    person_id = _str(params, "person_id")
    if not person_id:
        raise RequestRefused("invalid_params", "person_id is missing")
    person = await _change(
        ctx,
        "person updated",
        lambda: update_person(
            _workspace(ctx),
            person_id,
            name=_str(params, "name"),
            role_id=_str(params, "role_id"),
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
    roles = params.get("roles")
    if not isinstance(roles, dict):
        raise RequestRefused("invalid_params", "roles must be {role_id: {rights: [...], says?: str}}")
    name = await _caller_name(ctx)
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


def watch_people_changes(extensions: ExtensionManager, workspace_path: Path) -> Callable[[], None]:
    """Tell every connected extension when this workspace's people or roles change.

    Returns the unsubscribe function (called at shutdown).
    """
    bus = get_domain_event_bus()
    resolved = workspace_path.resolve()

    async def on_change(event: DomainEvent) -> None:
        try:
            if event.workspace_path.resolve() != resolved:
                return
        except OSError:
            return
        told = []
        for extension_id, live in extensions.snapshot().items():
            if await extensions.send_event(extension_id, EVENT_PEOPLE_CHANGED, {}):
                told.append(str(live.get("name") or extension_id))
        if told:
            log.info(f"⬆️ People changed — told {', '.join(told)}", what=event.payload.get("what"))

    bus.subscribe(DomainEventType.PEOPLE_CHANGED, on_change)
    return lambda: bus.unsubscribe(DomainEventType.PEOPLE_CHANGED, on_change)
