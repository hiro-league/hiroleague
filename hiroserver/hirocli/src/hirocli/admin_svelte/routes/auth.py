"""The admin's own sign-in (the plan's Phase 6), and one sign-in for the extensions' sites (Phase 8).

Every other ``/api`` route needs a signed-in session (``RequireSignIn`` below, added
as middleware in admin/run.py). Sign-ins belong to the workspace this server runs
(the hosting workspace), whichever workspace the admin is looking at.

Phase 8: a role either opens HiroLeague's settings (Owner always; others when switched on)
or not; someone whose role doesn't may call only the sign-in routes and ``/api/apps`` (the
dashboard's Apps card). An extension's site sends a signed-out browser here
(``/sign-in?for=<extension>&next=<path>``); once signed in, ``/api/auth/for/<extension>``
sends it back with a one-time code (runtime/sign_in_for_extensions.py). A connected extension
may offer a way to sign in (Home Assistant's login): ``/api/auth/with/<id>`` starts it there,
``/api/auth/with/callback`` finishes it.

The session cookie is HttpOnly, SameSite=Lax (Phase 8, was Strict: an extension's site sends the
browser here, and a Strict cookie isn't sent on that arrival), Secure when the request came over
https (Caddy says so in X-Forwarded-Proto), and named after the admin port so two workspaces'
admins on one machine don't share it.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from urllib.parse import urlencode

from fastapi import APIRouter, Request

from hirocli.admin_svelte.result_payload import api_failure
from fastapi.responses import JSONResponse, RedirectResponse
from hiro_channel_sdk.constants import METHOD_SIGN_IN_FINISH, METHOD_SIGN_IN_START
from hiro_channel_sdk.extension import ExtensionRequestError
from hiro_commons.log import Logger
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from hirocli.domain.admin_sign_in import (
    SESSION_DAYS,
    check_password,
    end_session,
    session_person,
    start_session,
)
from hirocli.domain.people import anyone_signs_in, get_person, get_role
from hirocli.runtime.sign_in_for_extensions import (
    CODES,
    app_entry,
    back_url,
    find_site,
    list_sign_in_offers,
    list_sites,
    local_path,
    sites_for_role,
)

log = Logger.get("ADMIN.AUTH")

auth_router = APIRouter()

AUTH_PREFIX = "/api/auth/"
# Phase 8: what someone whose role doesn't open HiroLeague's settings may still call.
LIMITED_PREFIXES = (AUTH_PREFIX, "/api/apps")
NOT_FOR_YOUR_ROLE = "Your role doesn't open HiroLeague's settings."

# Wrong passwords: at most this many per sign-in name in the window, then wait.
_MAX_FAILURES = 10
_FAILURE_WINDOW_S = 600.0
_failures: dict[str, deque[float]] = defaultdict(deque)


class SignInBody(BaseModel):
    sign_in: str
    password: str


def _workspace_path(request: Request) -> Path:
    ctx = request.app.state.ctx
    return Path(ctx.workspace_path)


def cookie_name(request: Request) -> str:
    return f"hiro_admin_{request.app.state.ctx.config.admin_port}"


def _over_https(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return forwarded == "https" or request.url.scheme == "https"


def _too_many_failures(name: str) -> bool:
    now = time.monotonic()
    tries = _failures[name]
    while tries and now - tries[0] > _FAILURE_WINDOW_S:
        tries.popleft()
    return len(tries) >= _MAX_FAILURES


def _public(person: Any) -> dict[str, Any]:
    return {"person_id": person.person_id, "name": person.name, "sign_in": person.sign_in, "role_id": person.role_id}


def _manager(request: Request) -> Any:
    return getattr(request.app.state.ctx, "extension_manager", None)


def _origin(request: Request) -> str:
    """This admin's address as the browser sees it (http://hiro.local behind Caddy)."""
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip() or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def _set_session_cookie(request: Request, response: Any, token: str) -> None:
    response.set_cookie(
        cookie_name(request),
        token,
        max_age=SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=_over_https(request),
        path="/",
    )


def _to_sign_in_page(for_extension: str, next_path: str, error: str | None = None) -> RedirectResponse:
    """Back to the sign-in page, keeping where the browser was going (and why it didn't get there)."""
    query = {k: v for k, v in (("for", for_extension), ("next", next_path), ("signin_error", error)) if v}
    return RedirectResponse(f"/sign-in?{urlencode(query)}" if query else "/sign-in", status_code=303)


def _role_opens_settings(workspace_path: Path, role_id: str) -> bool:
    role = get_role(workspace_path, role_id)
    return role is not None and role.admin


async def signed_in_person(request: Request) -> Any:
    """The person this request's session belongs to, or None."""
    token = request.cookies.get(cookie_name(request))
    if not token:
        return None
    return await run_in_threadpool(session_person, _workspace_path(request), token)


class RequireSignIn:
    """ASGI middleware: every /api route but /api/auth/* needs a signed-in session.

    Plain ASGI rather than Starlette's BaseHTTPMiddleware, which wraps streaming
    responses: the admin's live streams (SSE) pass through untouched.
    """

    def __init__(self, app: Any, ctx: Any) -> None:
        self.app = app
        self.workspace_path = Path(ctx.workspace_path)
        self.cookie = f"hiro_admin_{ctx.config.admin_port}"

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        path = scope.get("path", "") if scope.get("type") == "http" else ""
        if path.startswith("/api/") and not path.startswith(AUTH_PREFIX):
            token = Request(scope).cookies.get(self.cookie)
            person = await run_in_threadpool(session_person, self.workspace_path, token) if token else None
            if person is None:
                denied = api_failure("Sign in to the admin first.", 401)
                await denied(scope, receive, send)
                return
            # Phase 8: signed in for the apps only (Adult and Kid by default): the settings stay shut.
            if not path.startswith(LIMITED_PREFIXES):
                opens = await run_in_threadpool(_role_opens_settings, self.workspace_path, person.role_id)
                if not opens:
                    refused = api_failure(NOT_FOR_YOUR_ROLE, 403)
                    await refused(scope, receive, send)
                    return
        await self.app(scope, receive, send)


@auth_router.get("/auth/me")
async def who_am_i(request: Request) -> Any:
    person = await signed_in_person(request)
    workspace_path = _workspace_path(request)
    anyone = await run_in_threadpool(anyone_signs_in, workspace_path)
    role = await run_in_threadpool(get_role, workspace_path, person.role_id) if person else None
    # Phase 8: the ways to sign in connected extensions offer (the sign-in page's buttons).
    offers = [{"id": o.id, "label": o.label, "extension": o.extension} for o in list_sign_in_offers(_manager(request))]
    return {
            "signed_in": person is not None,
            "person": _public(person) if person else None,
            "role_name": role.name if role else None,
            "can_open_settings": bool(role and role.admin),
            "anyone_signs_in": anyone,
            "sign_in_offers": offers,
        }


@auth_router.post("/auth/sign-in")
async def sign_in(body: SignInBody, request: Request) -> JSONResponse:
    name = body.sign_in.strip().lower()
    if _too_many_failures(name):
        log.warning("⚠️ Admin sign-in refused — too many wrong passwords", sign_in=name)
        return api_failure("Too many wrong passwords. Wait a few minutes and try again.", 429)
    workspace_path = _workspace_path(request)
    person = await run_in_threadpool(check_password, workspace_path, body.sign_in, body.password)
    if person is None:
        _failures[name].append(time.monotonic())
        log.warning("⚠️ Admin sign-in failed — wrong name or password", sign_in=name)
        return api_failure("Wrong name or password.", 401)
    _failures.pop(name, None)
    token, _expires = await run_in_threadpool(start_session, workspace_path, person.person_id)
    log.info(f"✅ Admin signed in — {person.name}", sign_in=person.sign_in)
    response = JSONResponse({"person": _public(person)})
    _set_session_cookie(request, response, token)
    return response


async def _end_this_session(request: Request) -> None:
    person = await signed_in_person(request)
    await run_in_threadpool(end_session, _workspace_path(request), request.cookies.get(cookie_name(request)))
    if person is not None:
        log.info(f"Admin signed out — {person.name}", sign_in=person.sign_in)


async def _through_the_apps(request: Request, end_url: str, skip: str = "") -> str | None:
    """Phase 8, signing out of both: a browser address that passes through each connected app's site (ending this
    browser's session there, ``<site>/api/auth/signout?next=…``) and lands on ``end_url``; None when there is none.
    ``skip`` is the app that asked, already signed out."""
    sites = await run_in_threadpool(list_sites, _manager(request), _workspace_path(request))
    url = None
    for site in reversed([s for s in sites if s.online and skip not in (s.extension, s.extension_id)]):
        url = f"{site.url}/api/auth/signout?{urlencode({'next': url or end_url})}"
    return url


@auth_router.post("/auth/sign-out")
async def sign_out(request: Request) -> JSONResponse:
    await _end_this_session(request)
    # Phase 8: signing out of HiroLeague signs this browser out of the apps' sites too; the page goes there next.
    then = await _through_the_apps(request, f"{_origin(request)}/sign-in")
    response = JSONResponse({"then": then})
    response.delete_cookie(cookie_name(request), path="/")
    return response


@auth_router.get("/auth/sign-out")
async def sign_out_from_an_app(request: Request) -> RedirectResponse:
    """Phase 8: an app's Sign out (?for=<app>, already signed out there) ends this browser's HiroLeague session and
    any other app's, then shows the sign-in page, which goes back to that app after the next sign-in."""
    for_extension = request.query_params.get("for", "")
    await _end_this_session(request)
    end = f"{_origin(request)}/sign-in" + (f"?{urlencode({'for': for_extension})}" if for_extension else "")
    response = RedirectResponse(await _through_the_apps(request, end, skip=for_extension) or end, status_code=303)
    response.delete_cookie(cookie_name(request), path="/")
    return response


# ---------------------------------------------------------------------------
# Phase 8: one sign-in for the extensions' sites
# ---------------------------------------------------------------------------


@auth_router.get("/auth/for/{extension}")
async def sign_in_for(extension: str, request: Request, next: str = "/") -> RedirectResponse:
    """Send a signed-in browser back to an extension's site with a one-time code; else to the sign-in page."""
    person = await signed_in_person(request)
    if person is None:
        return _to_sign_in_page(extension, next)
    site = await run_in_threadpool(find_site, _manager(request), _workspace_path(request), extension)
    if site is None:
        log.warning("⚠️ Sign-in for an unknown site", extension=extension)
        return _to_sign_in_page("", "", f"No app called {extension} has a site to go back to.")
    code = CODES.make_code(site.extension_id, person.person_id)
    log.info(f"⬆️ Signed-in browser sent back — {person.name} · {site.title}", url=site.url)
    return RedirectResponse(back_url(site, code, next), status_code=303)


@auth_router.get("/auth/with/callback")
async def sign_in_with_callback(request: Request, code: str = "", state: str = "") -> RedirectResponse:
    """The offered sign-in came back: the extension says who it is; start a session here."""
    started = CODES.finish(state)
    if started is None or not code:
        return _to_sign_in_page("", "", "The sign-in didn't come back as it started (another tab, or it took too long).")
    manager = _manager(request)
    if manager is None:
        return _to_sign_in_page(started.for_extension, started.next_path, "The app that offers this sign-in isn't connected.")
    origin = _origin(request)
    params = {
        "method": started.method,
        "code": code,
        "client_id": f"{origin}/",
        "redirect_uri": f"{origin}/api/auth/with/callback",
    }
    try:
        answer = await manager.request(started.extension_id, METHOD_SIGN_IN_FINISH, params)
    except ExtensionRequestError as exc:
        log.warning("⚠️ Offered sign-in refused", method=started.method, error=str(exc))
        return _to_sign_in_page(started.for_extension, started.next_path, exc.message)
    workspace_path = _workspace_path(request)
    person = await run_in_threadpool(get_person, workspace_path, str(answer.get("person_id") or ""))
    if person is None:
        return _to_sign_in_page(started.for_extension, started.next_path, "That person isn't in the family list.")
    token, _expires = await run_in_threadpool(start_session, workspace_path, person.person_id)
    log.info(f"✅ Admin signed in — {person.name} · {started.method}")
    if started.for_extension:
        target = f"/api/auth/for/{started.for_extension}?{urlencode({'next': started.next_path})}"
    else:
        target = started.next_path or "/"
    response = RedirectResponse(target, status_code=303)
    _set_session_cookie(request, response, token)
    return response


def _offer(manager: Any, method: str) -> Any:
    """The first connected extension offering this way to sign in, or None. (The routes' ``next``
    parameter shadows the builtin, so the lookup lives here.)"""
    for offer in list_sign_in_offers(manager):
        if offer.id == method:
            return offer
    return None


@auth_router.get("/auth/with/{method}")
async def sign_in_with(method: str, request: Request, next: str = "/") -> RedirectResponse:
    """Start a way to sign in a connected extension offers (Home Assistant's login): off to its page."""
    for_extension = request.query_params.get("for", "")
    manager = _manager(request)
    offer = _offer(manager, method)
    if offer is None or manager is None:
        return _to_sign_in_page(for_extension, next, "That way to sign in isn't available right now.")
    state = CODES.start(offer.extension_id, method, for_extension, local_path(next))
    origin = _origin(request)
    params = {
        "method": method,
        "client_id": f"{origin}/",
        "redirect_uri": f"{origin}/api/auth/with/callback",
        "state": state,
    }
    try:
        answer = await manager.request(offer.extension_id, METHOD_SIGN_IN_START, params)
    except ExtensionRequestError as exc:
        log.warning(f"⚠️ Offered sign-in didn't start — {offer.label} · {offer.extension}", error=str(exc))
        return _to_sign_in_page(for_extension, next, f"{offer.label} sign-in didn't start: {exc.message}")
    url = str(answer.get("url") or "")
    if not url.startswith(("http://", "https://")):
        return _to_sign_in_page(for_extension, next, f"{offer.label} sign-in didn't start.")
    log.info(f"⬆️ Offered sign-in started — {offer.label} · {offer.extension}")
    return RedirectResponse(url, status_code=303)


@auth_router.get("/apps")
async def apps(request: Request) -> Any:
    """Phase 8: the extensions' sites this person's role sees (the dashboard's Apps card). The app switcher (UI kit)
    reads the same list, every app's own /api/apps alike: HiroLeague first, the app it is shown in marked ``here``
    (the Apps card leaves that one out)."""
    person = await signed_in_person(request)
    if person is None:
        return api_failure("Sign in first.", 401)
    sites = await run_in_threadpool(list_sites, _manager(request), _workspace_path(request))
    shown = sites_for_role(sites, person.role_id)
    core = {"extension": "hiroleague", "title": "HiroLeague", "icon": "hiroleague", "url": _origin(request),
            "online": True, "here": True}
    return {"apps": [core, *({**app_entry(s), "here": False} for s in shown)]}
