"""HiroLeague's family list in the app: who may sign in, with which role, and the numbers WhatsApp messages go to.

The core owns the family: its people (name, what Hiro calls them, WhatsApp number, role) and the roles, with what each
role may do in the app (`Role.rights`, granted in HiroLeague's People → Roles for the features the app declares,
`Extension.features`). The app keeps a copy (`CorePerson`, `Role`) and keeps only **No access** (`AppUser.denied`) as
its own.

A user is a core person: `AppUser.id` is the core's person id, and their role (`AppUser.role_id`) is a cache of that
person's role in the copy, else they wait (`recompute_roles`).

The copy is read from the core (`people.list`, through `hiroleague.link`) when the link connects, when the core says
`people.changed`, and every 10 minutes (events aren't queued, and changes made with the core's CLI send none): the
`FamilySync` worker. With the core down, the app keeps its last copy, so nobody is locked out. A change made here (a
user's role) is asked of the core first (`people.update`); the core's refusals ("the only Owner") come back as
`Invalid`, in its words. Open pages hear the notice "family".

An app that took a feature over from another (`Extension.rights_from`: NetHiro and TrainHiro, from HomeHiro) asks the
core once, on its first connection, to copy each role's rights there into the app's features
(`roles.import_rights {"copy_from": "home"}`, `_copy_rights_once`), so every role keeps exactly the rights it had.

Backend kit, step 3: each app had its own copy of this module, the same but for that.
"""

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from hiro_channel_sdk import ExtensionRequestError
from hiro_channel_sdk.constants import EVENT_PEOPLE_CHANGED, METHOD_PEOPLE_LIST, METHOD_PEOPLE_UPDATE, METHOD_ROLES_IMPORT_RIGHTS
from hiro_channel_sdk.workers import Worker
from sqlmodel import Session, select

from . import calls, identity, settings
from .db import run_db
from .errors import AppError, Invalid, OutsideError, Unavailable, failed, translate
from .events import bus
from .extension import ext
from .hiroleague import CONNECTED, link
from .models import AppUser, CorePerson, Role

log = identity.logger("family")

EVERY = 600.0  # seconds: the backstop read of the core's list
TIMEOUT = 15.0  # seconds per request to the core
# Setting: when each role's rights were copied from the app named in `Extension.rights_from` by the core (ISO time)
RIGHTS_COPIED = "rights_copied"


class FamilyError(OutsideError):
    """HiroLeague's family list failed, didn't answer, or answered something the app can't read (502)."""


@dataclass(frozen=True)
class FamilyPerson:
    """A person as the core lists them."""

    id: str
    name: str
    whatsapp: str
    role_id: str


@dataclass(frozen=True)
class CoreRole:
    """A role as the core lists it, with what it may do in the app."""

    id: str
    name: str
    built_in: bool
    says: str = ""
    rights: tuple[str, ...] = ()


def _now() -> datetime:
    return datetime.now(UTC)


def _no_core() -> str:
    return f"{identity.app().title} isn't connected to HiroLeague (Settings → HiroLeague)"


# --- asking the core -----------------------------------------------------------------------------------------------


async def ask(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """One request to the core's family list, timed; a refusal is `Invalid` in the core's words, not being connected
    `Unavailable`, anything else a `FamilyError`."""
    client = link.client
    if not client.connected:
        raise Unavailable(f"{_no_core()}: the family list can't be read or changed now")
    started = calls.start()
    try:
        answer = await client.request(method, params or {}, timeout=TIMEOUT)
    except ExtensionRequestError as exc:
        if exc.code == "invalid_params":  # the core's reason, written for people ("Mona is the only Owner…")
            raise Invalid(exc.message) from exc
        if exc.code == "not_connected":
            raise Unavailable(f"{_no_core()}: the family list can't be read or changed now") from exc
        if exc.code == "timeout":
            raise FamilyError(f"HiroLeague didn't answer in {TIMEOUT:.0f} s ({method})") from exc
        raise FamilyError(f"HiroLeague failed ({exc.code}): {exc.message}") from exc
    calls.done(log, f"Family: {method}", started, timeout=TIMEOUT)
    return answer


def _person(raw: Any) -> FamilyPerson:
    with translate(FamilyError, "HiroLeague's answer about a person can't be read"):
        return FamilyPerson(id=str(raw["person_id"]), name=str(raw["name"]), whatsapp=str(raw.get("whatsapp") or ""),
                            role_id=str(raw["role_id"]))


def _calls_them(raw: Any) -> str:
    return str((raw or {}).get("calls_them") or "")


def _role(raw: Any) -> CoreRole:
    with translate(FamilyError, "HiroLeague's answer about a role can't be read"):
        return CoreRole(id=str(raw["role_id"]), name=str(raw["name"]), built_in=bool(raw.get("built_in")),
                        says=str(raw.get("says") or ""), rights=tuple(str(k) for k in raw.get("rights") or ()))


# --- writing the copy ----------------------------------------------------------------------------------------------


def _store_person(session: Session, p: FamilyPerson, calls_them: str, now: datetime) -> bool:
    """Put one core person into the copy; True when something changed."""
    row = session.get(CorePerson, p.id)
    if row is None:
        session.add(CorePerson(id=p.id, name=p.name, calls_them=calls_them, whatsapp=p.whatsapp, role_id=p.role_id,
                               synced_at=now))
        return True
    changed = (row.name, row.calls_them, row.whatsapp, row.role_id) != (p.name, calls_them, p.whatsapp, p.role_id)
    row.name, row.calls_them, row.whatsapp, row.role_id, row.synced_at = p.name, calls_them, p.whatsapp, p.role_id, now
    session.add(row)
    return changed


def _sync_roles(session: Session, core: list[CoreRole], now: datetime) -> list[str]:
    """The app's roles become the core's: added, renamed, their lines and rights, removed; what changed, in words.
    Every role is the core's (the app has no roles of its own), so the copy simply follows the list."""
    said: list[str] = []
    local = {r.id: r for r in session.exec(select(Role))}
    wanted = {c.id: c for c in core}
    for rid, r in local.items():
        if rid in wanted:
            continue
        for u in session.exec(select(AppUser).where(AppUser.role_id == rid)):
            u.role_id = None
            session.add(u)
        session.flush()
        session.delete(r)
        said.append(f"role {r.name} removed")
    session.flush()
    # Role.name is unique and the core may swap two names: a name that changes takes a placeholder first
    renamed = [c for c in core if c.id in local and local[c.id].name != c.name]
    for c in renamed:
        local[c.id].name = f"\x00{c.id}"
        session.add(local[c.id])
    session.flush()
    for c in core:
        r = local.get(c.id)
        if r is None:
            session.add(Role(id=c.id, name=c.name, says=c.says, built_in=c.built_in, core=True, rights=list(c.rights),
                             created_at=now, updated_at=now))
            said.append(f"role {c.name} added")
            continue
        before = (r.name, r.says, r.built_in, list(r.rights))
        if r.name.startswith("\x00"):
            said.append(f"role {c.name} renamed")
        elif list(r.rights) != list(c.rights):
            said.append(f"what {c.name} may do changed")
        r.name, r.says, r.built_in, r.core, r.rights = c.name, c.says, c.built_in, True, list(c.rights)
        if before != (r.name, r.says, r.built_in, list(r.rights)):
            r.updated_at = now
        session.add(r)
    session.flush()
    return said


def _apply(session: Session, people: list[tuple[FamilyPerson, str]], roles: list[CoreRole]) -> list[str]:
    """Write the core's list into the copy and recompute the users' roles; what changed, in words."""
    now = _now()
    said = _sync_roles(session, roles, now)
    seen = {p.id for p, _ in people}
    added = changed = 0
    for row in session.exec(select(CorePerson)):
        if row.id not in seen:
            session.delete(row)
            said.append(f"{row.name} left the family list")
    for p, calls_them in people:
        fresh = session.get(CorePerson, p.id) is None
        if _store_person(session, p, calls_them, now):
            added, changed = added + fresh, changed + (not fresh)
    if added:
        said.append(f"{added} added")
    if changed:
        said.append(f"{changed} changed")
    session.flush()
    said += recompute_roles(session)
    session.commit()
    return said


def _user_role(session: Session, u: AppUser, roles: set[str]) -> str | None:
    """A user's role: their core person's, when the app's copy has that role; else None (they wait)."""
    core = session.get(CorePerson, u.id)
    return core.role_id if core and core.role_id in roles else None


def recompute_roles(session: Session) -> list[str]:
    """Every user's role from the family list; what changed, in words. Not committed."""
    said = []
    names = {r.id: r.name for r in session.exec(select(Role))}
    for u in session.exec(select(AppUser)):
        role = _user_role(session, u, set(names))
        if role != u.role_id:
            log.info("Family: %s's role is now %s (from HiroLeague's family list)", u.name, names.get(role or "", "none: waiting"))
            u.role_id = role
            session.add(u)
            said.append(f"{u.name}'s role changed")
    return said


def recompute_user(session: Session, u: AppUser) -> None:
    """One user's role from the family list, when they come in (auth/api.py `seen`). Not committed."""
    u.role_id = _user_role(session, u, set(session.exec(select(Role.id))))


# --- the sync ------------------------------------------------------------------------------------------------------


lock = asyncio.Lock()  # one sync at a time (the worker's rounds, and the ones after a change made here)


async def _copy_rights_once() -> None:
    """Ask the core once to give each role, in the app's features, the rights it has in the app it took a feature
    over from (`Extension.rights_from`): the core fills only roles with no rights here yet, so nothing the owner set is
    overwritten. Not done (an older core, or not answering): logged, and asked again on the next round."""
    source, what = ext().rights_from, ext().rights_from_what
    if source is None or await run_db(settings.get, RIGHTS_COPIED) is not None:
        return
    try:
        answer = await ask(METHOD_ROLES_IMPORT_RIGHTS, {"copy_from": source})
    except AppError as exc:
        failed(log, f"Family: copying each role's {what} rights from {_app_named(source)} (asked again next round)", exc)
        return
    await run_db(_mark_rights_copied)
    log.info("Family: HiroLeague copied each role's rights from %s (%s filled); HiroLeague's are followed",
             _app_named(source), ", ".join(answer.get("imported") or []) or "no role")


def _app_named(extension: str) -> str:
    """An extension's name as people know it, for the log: "home" is HomeHiro."""
    return "HomeHiro" if extension == "home" else extension


def _mark_rights_copied(session: Session) -> None:
    settings.put(session, RIGHTS_COPIED, _now().isoformat())
    session.commit()


async def sync() -> list[str]:
    """Read the core's list into the copy; what changed, in words. Raises when the core can't be asked."""
    async with lock:
        await _copy_rights_once()  # before the list: the roles then come with the rights copied
        answer = await ask(METHOD_PEOPLE_LIST)
        with translate(FamilyError, "HiroLeague's family list can't be read"):
            people = [(_person(p), _calls_them(p)) for p in answer["people"]]
            roles = [_role(r) for r in answer["roles"]]
        said = await run_db(_apply, people, roles)
    if said:
        log.info("Family: synced with HiroLeague (%d people, %d roles): %s", len(people), len(roles), ", ".join(said))
        bus.publish("family")
    else:
        log.debug("Family: synced with HiroLeague (%d people, %d roles), nothing changed", len(people), len(roles))
    return said


class FamilySync(Worker):
    """Keeps the copy of the core's family list: when the link connects, when the core says it changed, and every 10
    minutes."""

    name = "family"

    def __init__(self) -> None:
        super().__init__()
        self._due: asyncio.Event | None = None
        self._unsubscribe = None

    def on_start(self) -> None:
        self._due = asyncio.Event()
        self._unsubscribe = bus.subscribe(CONNECTED, self._now)
        link.client.on_event(EVENT_PEOPLE_CHANGED, self._changed)
        self.spawn(self._loop(), "sync")

    def on_stop(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    def _now(self, _kind: str, _data: Any) -> None:
        if self._due is not None:
            self._due.set()

    async def _changed(self, _event: str, _data: dict[str, Any]) -> None:
        log.debug("Family: HiroLeague says the family list changed")
        self._now("", None)

    async def _loop(self) -> None:
        assert self._due is not None
        while True:
            with suppress(TimeoutError):
                await asyncio.wait_for(self._due.wait(), EVERY)
            self._due.clear()
            if not self.running:
                return
            if not link.client.connected:
                continue  # keeps the last copy; the next connect asks again
            try:
                await sync()
            except Exception as exc:  # one bad round never ends the loop; logged, the next round tries again
                failed(log, "Family: reading HiroLeague's family list", exc)


worker = FamilySync()


async def sync_soon() -> None:
    """After a change made here: read the list again now. A failure is logged: the change itself was made."""
    try:
        await sync()
    except AppError as exc:
        failed(log, "Family: reading HiroLeague's family list after a change", exc)


# --- changes asked of the core -------------------------------------------------------------------------------------


def _store_and_recompute(session: Session, p: FamilyPerson, calls_them: str) -> None:
    _store_person(session, p, calls_them, _now())
    session.flush()
    recompute_roles(session)
    session.commit()


async def update_person(core_person_id: str, **fields: str) -> FamilyPerson:
    """Change a core person (name, role_id, calls_them, whatsapp): asked of the core, then written to the copy."""
    answer = await ask(METHOD_PEOPLE_UPDATE, {"person_id": core_person_id, **fields})
    raw = answer.get("person")
    p = _person(raw)
    async with lock:  # a sync started by the core's "people changed" may be writing the same row
        await run_db(_store_and_recompute, p, _calls_them(raw))
    bus.publish("family")
    return p


def reachable(session: Session, core_person_id: str) -> CorePerson:
    """The core person a WhatsApp message goes to, with a number; raises Invalid saying why not."""
    core = session.get(CorePerson, core_person_id)
    if core is None:
        raise Invalid(f"{core_person_id} isn't in HiroLeague's family list (any more)")
    if not core.whatsapp:
        raise Invalid(f"{core.name} has no WhatsApp number in HiroLeague")
    return core
