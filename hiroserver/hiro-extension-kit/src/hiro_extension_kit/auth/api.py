"""Users and roles: who is asking (/api/me), signing in through HiroLeague, and the owner's Settings → Users and
Settings → Roles.

A user is a person in HiroLeague's family list (`AppUser.id` is the core's person id). A signed-out browser is sent to
the core's sign-in page (`/api/auth/start`), which sends it back with a one-time code (`/api/auth/hiro`); the app asks
the core whose code it is (`auth.code`) and keeps its own 90-day session (sessions.py).

A user's role is their core person's role (family.py). Picking a role for a user changes it in the core
(people.update). The roles themselves (new, renamed, removed), their lines and what each may do in the app are set
in HiroLeague's People → Roles; Settings → Roles here shows them. No access stays the app's own. The app's features
and rights are its `Extension.features` (access.py); every route's check is guard.py.
"""

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from .. import family, identity, switchboard
from ..db import get_session, run_db
from ..errors import Invalid, AppError, NotAllowed, NotFound, NotSignedIn, failed
from ..extension import ext
from ..hiroleague import link
from .models import AppUser, CorePerson, Role
from . import sessions
from .one_sign_in import after_core_sign_out, local_path, redeem, sign_in_url, sign_out_url
from .access import OWNER, levels, rights_of
from .identity import Caller, caller_of, device_of

log = identity.logger("auth")
router = APIRouter(prefix="/api")

SEEN_EVERY = timedelta(minutes=5)  # how often "last here" is written for someone who keeps using the app


def _now() -> datetime:
    return datetime.now(UTC)


def _title() -> str:
    return identity.app().title  # "NetHiro", in messages


def _signed_in_user(session: Session, token: str) -> AppUser | None:
    uid = sessions.user_of(session, token)
    return session.get(AppUser, uid) if uid else None


def not_linked(name: str) -> str:
    """Why someone the app's other way in names waits: not linked to anyone in the family list (the app's words)."""
    other = ext().other_way
    return other.not_linked(name) if other else ""


async def caller(request: Request) -> Caller:
    """Who sent this request: signed in here (the session cookie), the app's other way in (HomeHiro: HA's add-on,
    mapped to the core person through its links; user_id "" when not linked), or sign-in off. In a test environment
    whose switchboard turns the sign-in screen off, everyone is the owner, or the one person it names (with their
    role, from the family list, as if they had signed in)."""
    quick = switchboard.sign_in()
    if quick.mode == "as":
        return Caller(quick.person, quick.name or quick.person, "web", device_of(request.headers.get("user-agent", "")))
    c = caller_of(request.headers, ext().auth and not quick.quick)
    if c is not None:
        return c
    other = ext().other_way
    if other is not None and (c := other.caller(request.headers)) is not None:
        named = c
        return await run_db(lambda s: dataclasses.replace(named, user_id=other.person_of(s, named.other_id)))
    token = request.cookies.get(sessions.COOKIE, "")
    if token:
        user = await run_db(_signed_in_user, token)
        if user:
            return Caller(user.id, user.name, "web", device_of(request.headers.get("user-agent", "")))
    raise NotSignedIn(f"Sign in at HiroLeague to use {_title()}.")


async def owner(request: Request) -> Caller:
    """Only an owner manages users and roles (and everyone, with sign-in off)."""
    c = await caller(request)
    if c.way == "dev":
        return c
    user = await run_db(lambda s: s.get(AppUser, c.user_id)) if c.user_id else None
    if user is None or user.role_id != OWNER:
        raise NotAllowed("Only an owner can manage users and roles.")
    return c


# ---- who is asking


class PlaceSystem(BaseModel):
    id: str  # the switchboard's name for it ("ha")
    name: str  # for people ("Home Assistant")
    mode: Literal["real", "read", "fake", "off"]


class PlaceOut(BaseModel):
    """A test environment and what it reaches of the outside systems this app uses (its switchboard): the banner on
    every page there."""

    place: str  # "env2"
    preset: str  # "Safe"
    problem: str = ""  # the switchboard couldn't be read: every system is off
    sign_in: Literal["on", "off", "as"] = "on"  # off: no sign-in screen, everyone is the owner; as: everyone is one person
    sign_in_as: str = ""  # "as": that person's name
    systems: list[PlaceSystem] = []


def _place() -> PlaceOut | None:
    here = switchboard.page()
    return PlaceOut.model_validate(here) if here else None


class MeOut(BaseModel):
    id: str  # the core person's id ("" for someone the other way in names, not linked to one yet)
    name: str
    way: Literal["ha", "web", "dev"]
    state: Literal["ok", "waiting", "denied"]  # waiting: no role yet; denied: the owner chose No access
    role_id: str | None
    role_name: str | None
    owner: bool
    access: dict[str, Literal["no", "see", "use"]]  # every feature's level (from the rights: "use" = any beyond See)
    rights: list[str] = []  # the exact rights ("<feature>.<right>"); the routes check these
    reason: str = ""  # why they wait, for people ("" = waiting for a role)
    place: PlaceOut | None = Field(default_factory=_place)  # None in live and env0: everything is real there


def seen(session: Session, c: Caller) -> AppUser:
    """The user for this caller (a core person), made the first time; their role from the family list; "last here"
    kept roughly up to date."""
    now = _now()
    core = session.get(CorePerson, c.user_id)
    name = core.name if core else c.name  # they are a person in the family list: their name there
    u = session.get(AppUser, c.user_id)
    if u is None:
        u = AppUser(id=c.user_id, name=name, first_seen=now, last_seen=now, last_way=c.way, last_device=c.device)
        family.recompute_user(session, u)  # their role: their core person's
        session.add(u)
        session.commit()
        log.info("Users: %s opened %s for the first time (%s, %s)%s", name, _title(), c.way, c.device,
                 "" if u.role_id else ", waiting for a role")
        return u
    before = u.role_id
    family.recompute_user(session, u)
    changed = u.role_id != before
    if (u.name, u.last_way, u.last_device) != (name, c.way, c.device) or now - u.last_seen >= SEEN_EVERY:
        u.name, u.last_way, u.last_device, u.last_seen = name, c.way, c.device, now
        changed = True
    if changed:
        session.add(u)
        session.commit()
    return u


def _me(session: Session, u: AppUser) -> MeOut:
    role = session.get(Role, u.role_id) if u.role_id else None
    state = "denied" if u.denied else "waiting" if role is None else "ok"
    role_id = role.id if role and state == "ok" else None
    return MeOut.model_validate({
        "id": u.id, "name": u.name, "way": u.last_way or "web", "state": state, "role_id": role_id,
        "role_name": role.name if role_id and role else None, "owner": role_id == OWNER,
        "access": levels(role_id, role.rights if role else []),
        "rights": rights_of(role_id, role.rights if role else []),
    })


@router.get("/me")
async def me(request: Request) -> MeOut:
    """Who is asking, and what their role lets them do: every page asks first."""
    c = await caller(request)
    if c.way == "dev":
        return MeOut(id=c.user_id, name=c.name, way="dev", state="ok", role_id=OWNER, role_name="Owner", owner=True,
                     access=levels(OWNER, []), rights=rights_of(OWNER, []))
    if not c.user_id:  # the other way in names someone not linked to a core person: no user row, they wait
        return MeOut(id="", name=c.name, way=c.way, state="waiting", role_id=None, role_name=None, owner=False,
                     access=levels(None, []), reason=not_linked(c.name))
    return await run_db(lambda s: _me(s, seen(s, c)))


# ---- Signing in through HiroLeague (Phase 8: one sign-in)


def _failed_sign_in(message: str) -> RedirectResponse:
    return RedirectResponse("/?signin_error=" + quote(message), 303)


@router.get("/auth/start")
async def sign_in(next: str = "/") -> RedirectResponse:
    """A signed-out browser goes to HiroLeague's sign-in page, which sends it back to /api/auth/hiro with a one-time
    code."""
    url = sign_in_url(link, next)
    if url is None:
        other = ext().other_way
        ask = f"{other.elsewhere}ask the owner" if other and other.elsewhere else "Ask the owner"
        return _failed_sign_in(f"{_title()} doesn't know HiroLeague's address yet, so it can't send you there to sign in. "
                               f"{ask} to set it (Settings → HiroLeague).")
    return RedirectResponse(url, 303)


def _start_session(session: Session, c: Caller) -> str:
    sessions.purge(session)
    seen(session, c)
    return sessions.start(session, c.user_id, c.device)


@router.get("/auth/hiro")
async def signed_in_at_hiroleague(request: Request, code: str = "", next: str = "/") -> RedirectResponse:
    """HiroLeague sent the browser back with a one-time code: ask the core whose it is, start the app's own session
    (90 days), go where they were going. A failure goes back to the app's first page, which says why."""
    try:
        who = await redeem(link, code)
    except AppError as exc:
        failed(log, "Signing in through HiroLeague", exc)
        return _failed_sign_in(str(exc))
    person_id = str(who["person_id"])
    if not await run_db(lambda s: s.get(CorePerson, person_id) is not None):
        await family.sync_soon()  # someone new in the family list: their role is in the copy once it is read again
    c = Caller(person_id, str(who.get("name") or person_id), "web", device_of(request.headers.get("user-agent", "")))
    token = await run_db(_start_session, c)
    log.info("Users: %s signed in through HiroLeague (%s)", c.name, c.device)
    r = RedirectResponse(local_path(next), 303)
    r.set_cookie(sessions.COOKIE, token, max_age=sessions.SESSION_DAYS * 86400, httponly=True, samesite="lax", path="/")
    return r


class SignedOut(BaseModel):
    then: str | None  # where the browser goes next to be signed out of HiroLeague too; None = nowhere


async def _end_this_session(request: Request) -> None:
    token = request.cookies.get(sessions.COOKIE, "")
    await run_db(lambda s: sessions.end(s, token))


@router.post("/auth/logout")
async def sign_out(request: Request) -> Response:
    """Sign out, of HiroLeague too. The app's session ends here; the page then goes to HiroLeague's sign-out, which ends
    that one and shows its sign-in page, back to the app after the next sign-in."""
    await _end_this_session(request)
    r = Response(SignedOut(then=sign_out_url(link)).model_dump_json(), media_type="application/json")
    r.delete_cookie(sessions.COOKIE, path="/")
    return r


@router.get("/auth/signout")
async def signed_out_by_hiroleague(request: Request, next: str = "/") -> RedirectResponse:
    """HiroLeague's Sign out passes the browser through here (signing out of both): the app's session in this browser
    ends, then on to `next`, only ever back to HiroLeague's own address (anything else: the app's first page)."""
    await _end_this_session(request)
    r = RedirectResponse(after_core_sign_out(link, next), 303)
    r.delete_cookie(sessions.COOKIE, path="/")
    return r


# ---- Settings → Users


class Ref(BaseModel):
    id: str
    name: str


class UserOut(BaseModel):
    id: str  # the core person's id
    name: str
    role_id: str | None
    denied: bool
    first_seen: datetime
    last_seen: datetime
    last_way: str
    last_device: str
    # Only in an app with a users scope (Extension.users_scope, HomeHiro's My room): the linked person, their things,
    # and what is picked
    person: Ref | None = None
    person_things: list[Ref] | None = None
    areas: list[str] | None = None
    things: list[str] | None = None


class UserIn(BaseModel):
    role_id: str | None = None  # None with denied: No access
    denied: bool = False
    areas: list[str] | None = None  # an app with a users scope: what is picked (None: as it was)
    things: list[str] | None = None


def users_out(session: Session) -> list[UserOut]:
    scope = ext().users_scope
    return [UserOut.model_validate({**u.model_dump(), **(scope.read(session, u) if scope else {})})
            for u in session.exec(select(AppUser).order_by(col(AppUser.first_seen)))]


@router.get("/users")
def list_users(_c: Caller = Depends(owner), session: Session = Depends(get_session)) -> list[UserOut]:
    return users_out(session)


def _checked_user(session: Session, user_id: str, body: UserIn) -> tuple[AppUser, Role | None, CorePerson | None]:
    """The user, the role picked (None: No access) and the core person whose role it sets; raises what's wrong."""
    u = session.get(AppUser, user_id)
    if u is None:
        raise NotFound(f"No such user: they appear here once they have opened {_title()}.")
    role = None
    if not body.denied:
        role = session.get(Role, body.role_id) if body.role_id else None
        if role is None:
            raise Invalid("Pick a role, or No access.")
    elif u.role_id == OWNER and not u.denied:  # No access is the app's own: the only owner keeps theirs here
        owners = session.exec(select(AppUser).where(AppUser.role_id == OWNER, col(AppUser.denied).is_(False))).all()
        if len(owners) == 1:
            raise Invalid(f"{u.name} is the only owner. Make someone else an owner first.")
    scope = ext().users_scope
    if scope is not None:
        scope.check(session, u, body.areas or [], body.things or [])
    core = session.get(CorePerson, user_id)  # the user is this core person
    if role is not None and role.id != u.role_id and core is None:
        raise Invalid(f"{u.name} isn't in HiroLeague's family list any more, so their role can't be set here.")
    return u, role, core


def _write_user(session: Session, user_id: str, body: UserIn) -> list[UserOut]:
    row = session.get(AppUser, user_id)
    if row is None:
        raise NotFound(f"No such user: they appear here once they have opened {_title()}.")
    row.denied = body.denied
    session.add(row)
    scope = ext().users_scope
    if scope is not None and (body.areas is not None or body.things is not None):
        scope.write(session, row, list(dict.fromkeys(body.areas or [])), list(dict.fromkeys(body.things or [])))
    session.flush()
    family.recompute_roles(session)
    session.commit()
    return users_out(session)


@router.put("/users/{user_id}")
async def put_user(user_id: str, body: UserIn, c: Caller = Depends(owner)) -> list[UserOut]:
    """A user's role (asked of HiroLeague: their core person's role; it refuses taking the only Owner's away and says
    why), or No access, and with a users scope what is picked there (both the app's own)."""
    u, role, core = await run_db(_checked_user, user_id, body)
    if role is not None and core is not None and role.id != u.role_id and role.id != core.role_id:
        await family.update_person(core.id, role_id=role.id)
    out = await run_db(_write_user, user_id, body)
    log.info("Users: %s gave %s %s", c.name, u.name, f"the role {role.name}" if role else "No access")
    return out


# ---- Settings → Roles


class RightOut(BaseModel):
    id: str
    name: str
    says: str


class FeatureOut(BaseModel):
    id: str
    name: str
    rights: list[RightOut]
    not_for_owner: bool


class RoleOut(BaseModel):
    id: str
    name: str
    says: str
    built_in: bool
    core: bool  # in HiroLeague's family list (every role the app keeps is: the copy follows the core's)
    rights: list[str]  # what it may do in the app, granted in HiroLeague ("<feature>.<right>")
    access: dict[str, Literal["no", "see", "use"]]  # every feature's level, from the rights
    users: list[str]  # the names of the users who have it


class RolesOut(BaseModel):
    roles: list[RoleOut]
    features: list[FeatureOut]
    admin_url: str = ""  # the core's admin ("" while unknown): its People → Roles is where roles change


def roles_out(session: Session) -> RolesOut:
    users = session.exec(select(AppUser).where(col(AppUser.role_id).is_not(None)).order_by(col(AppUser.name))).all()
    roles = session.exec(select(Role).order_by(col(Role.built_in).desc(), col(Role.created_at))).all()
    return RolesOut(
        roles=[RoleOut.model_validate({**r.model_dump(), "rights": rights_of(r.id, r.rights),
                                       "access": levels(r.id, r.rights),
                                       "users": [u.name for u in users if u.role_id == r.id]}) for r in roles],
        features=[FeatureOut.model_validate(f.model_dump()) for f in ext().features],
        admin_url=link.admin_url(),
    )


@router.get("/roles")
def list_roles(_c: Caller = Depends(owner), session: Session = Depends(get_session)) -> RolesOut:
    """Settings → Roles (read-only): the roles and what each may do in the app, as HiroLeague grants them."""
    return roles_out(session)
