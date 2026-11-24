"""Users and roles: who is asking (/api/me), signing in through HiroLeague, and the owner's Settings → Users and
Settings → Roles.

A user is a person in HiroLeague's family list (`AppUser.id` is the core's person id). A signed-out browser is sent to
the core's sign-in page (`/api/auth/start`), which sends it back with a one-time code (`/api/auth/hiro`); the app asks
the core whose code it is (`auth.code`) and keeps its own 90-day session (sessions.py).

A user's roles are their core person's roles (family.py): one or several, and their rights add up. Picking them for a
user changes them in the core (people.update). The roles themselves (new, renamed, removed), their lines and what each
may do in the app are set in HiroLeague's People → Roles; Settings → Roles here shows them. No access stays the app's
own. The app's features and actions are its `Extension.features` (access.py); every route's check is guard.py.
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
from .access import OWNER, levels, of_user, rights_of
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
    if user is None or user.denied or OWNER not in user.role_ids:
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
    role_ids: list[str]  # every role they hold, in the roles' order ([] while waiting or denied)
    role_names: list[str]
    owner: bool
    access: dict[str, Literal["no", "see", "use"]]  # every feature's level, their roles added up ("use" = any beyond See)
    # The keys their roles add up to ("<feature>.<action>", or ending ":own" for their own things); the routes check these
    rights: list[str] = []
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
    roles = of_user(session, u)
    names = {r.id: r.name for r in session.exec(select(Role).where(col(Role.id).in_(list(roles))))}
    state = "denied" if u.denied else "ok" if roles else "waiting"
    return MeOut.model_validate({
        "id": u.id, "name": u.name, "way": u.last_way or "web", "state": state, "role_ids": list(roles),
        "role_names": [names[r] for r in roles], "owner": OWNER in roles,
        "access": levels(roles), "rights": rights_of(roles),
    })


@router.get("/me")
async def me(request: Request) -> MeOut:
    """Who is asking, and what their role lets them do: every page asks first."""
    c = await caller(request)
    if c.way == "dev":
        owner = {OWNER: []}
        return MeOut(id=c.user_id, name=c.name, way="dev", state="ok", role_ids=[OWNER], role_names=["Owner"],
                     owner=True, access=levels(owner), rights=rights_of(owner))
    if not c.user_id:  # the other way in names someone not linked to a core person: no user row, they wait
        return MeOut(id="", name=c.name, way=c.way, state="waiting", role_ids=[], role_names=[], owner=False,
                     access=levels({}), reason=not_linked(c.name))
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
    role_ids: list[str]  # the roles they hold that the app's copy has, in the roles' order ([]: they wait)
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
    role_ids: list[str] | None = None  # every role they are to hold (set in the core); None: as they are
    denied: bool | None = None  # No access, the app's own; None: as it is
    areas: list[str] | None = None  # an app with a users scope: what is picked (None: as it was)
    things: list[str] | None = None


def users_out(session: Session) -> list[UserOut]:
    scope = ext().users_scope
    return [UserOut.model_validate({**u.model_dump(), **(scope.read(session, u) if scope else {})})
            for u in session.exec(select(AppUser).order_by(col(AppUser.first_seen)))]


@router.get("/users")
def list_users(_c: Caller = Depends(owner), session: Session = Depends(get_session)) -> list[UserOut]:
    return users_out(session)


def _checked_user(session: Session, user_id: str, body: UserIn) -> tuple[AppUser, list[Role], CorePerson | None]:
    """The user, the roles picked (in the roles' order) and the core person whose roles they set; raises what's wrong.
    """
    u = session.get(AppUser, user_id)
    if u is None:
        raise NotFound(f"No such user: they appear here once they have opened {_title()}.")
    wanted = list(dict.fromkeys(body.role_ids if body.role_ids is not None else u.role_ids))
    roles = [r for r in session.exec(select(Role).order_by(col(Role.built_in).desc(), col(Role.created_at)))
             if r.id in wanted]
    if len(roles) < len(wanted):
        raise Invalid("A role picked isn't in HiroLeague's family list any more.")
    denied = u.denied if body.denied is None else body.denied
    if not denied and not roles:
        raise Invalid("Pick a role, or No access.")
    if denied and not u.denied and OWNER in u.role_ids:  # No access is the app's own: the only owner keeps theirs here
        owners = [o for o in session.exec(select(AppUser).where(col(AppUser.denied).is_(False))) if OWNER in o.role_ids]
        if len(owners) == 1:
            raise Invalid(f"{u.name} is the only owner. Make someone else an owner first.")
    scope = ext().users_scope
    if scope is not None:
        scope.check(session, u, body.areas or [], body.things or [])
    core = session.get(CorePerson, user_id)  # the user is this core person
    if body.role_ids is not None and [r.id for r in roles] != list(u.role_ids) and core is None:
        raise Invalid(f"{u.name} isn't in HiroLeague's family list any more, so their roles can't be set here.")
    return u, roles, core


def _write_user(session: Session, user_id: str, body: UserIn) -> list[UserOut]:
    row = session.get(AppUser, user_id)
    if row is None:
        raise NotFound(f"No such user: they appear here once they have opened {_title()}.")
    if body.denied is not None:
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
    """A user's roles (asked of HiroLeague: their core person's roles; it refuses taking the only Owner's away and says
    why), No access, and with a users scope what is picked there (both the app's own)."""
    u, roles, core = await run_db(_checked_user, user_id, body)
    ids = [r.id for r in roles]
    if body.role_ids is not None and core is not None and ids != list(core.role_ids):
        await family.update_person(core.id, role_ids=ids)
    out = await run_db(_write_user, user_id, body)
    if body.denied:
        log.info("Users: %s gave %s No access", c.name, u.name)
    else:
        log.info("Users: %s gave %s the roles %s", c.name, u.name, ", ".join(r.name for r in roles))
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
    rights: list[str]  # what it may do in the app, granted in HiroLeague ("<feature>.<action>", or ending ":own")
    access: dict[str, Literal["no", "see", "use"]]  # every feature's level, from the rights
    users: list[str]  # the names of the users who hold it (one may hold several roles)


class RolesOut(BaseModel):
    roles: list[RoleOut]
    features: list[FeatureOut]
    admin_url: str = ""  # the core's admin ("" while unknown): its People → Roles is where roles change


def roles_out(session: Session) -> RolesOut:
    users = session.exec(select(AppUser).order_by(col(AppUser.name))).all()
    roles = session.exec(select(Role).order_by(col(Role.built_in).desc(), col(Role.created_at))).all()
    return RolesOut(
        roles=[RoleOut.model_validate({**r.model_dump(), "rights": rights_of({r.id: r.rights}),
                                       "access": levels({r.id: r.rights}),
                                       "users": [u.name for u in users if r.id in u.role_ids]}) for r in roles],
        features=[FeatureOut.model_validate(f.model_dump()) for f in ext().features],
        admin_url=link.admin_url(),
    )


@router.get("/roles")
def list_roles(_c: Caller = Depends(owner), session: Session = Depends(get_session)) -> RolesOut:
    """Settings → Roles (read-only): the roles and what each may do in the app, as HiroLeague grants them."""
    return roles_out(session)
