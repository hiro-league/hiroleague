"""The admin's own sign-in (the plan's Phase 6): who is signed in, sign in, sign out.

Every other ``/api`` route needs a signed-in session (``RequireSignIn`` below, added
as middleware in admin/run.py). Sign-ins belong to the workspace this server runs
(the hosting workspace), whichever workspace the admin is looking at. Anyone signed in
can do everything in the admin; there are no checks per role in Phase 6.

The session cookie is HttpOnly and SameSite=Strict, Secure when the request came over
https (Caddy says so in X-Forwarded-Proto), and named after the admin port so two
workspaces' admins on one machine don't share it.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
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
from hirocli.domain.people import anyone_signs_in

log = Logger.get("ADMIN.AUTH")

auth_router = APIRouter()

AUTH_PREFIX = "/api/auth/"

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
                denied = JSONResponse({"ok": False, "error": "Sign in to the admin first.", "data": None}, status_code=401)
                await denied(scope, receive, send)
                return
        await self.app(scope, receive, send)


@auth_router.get("/auth/me")
async def who_am_i(request: Request) -> dict[str, Any]:
    person = await signed_in_person(request)
    anyone = await run_in_threadpool(anyone_signs_in, _workspace_path(request))
    return {
        "ok": True,
        "error": None,
        "data": {"signed_in": person is not None, "person": _public(person) if person else None, "anyone_signs_in": anyone},
    }


@auth_router.post("/auth/sign-in")
async def sign_in(body: SignInBody, request: Request) -> JSONResponse:
    name = body.sign_in.strip().lower()
    if _too_many_failures(name):
        log.warning("⚠️ Admin sign-in refused — too many wrong passwords", sign_in=name)
        return JSONResponse(
            {"ok": False, "error": "Too many wrong passwords. Wait a few minutes and try again.", "data": None},
            status_code=429,
        )
    workspace_path = _workspace_path(request)
    person = await run_in_threadpool(check_password, workspace_path, body.sign_in, body.password)
    if person is None:
        _failures[name].append(time.monotonic())
        log.warning("⚠️ Admin sign-in failed — wrong name or password", sign_in=name)
        return JSONResponse({"ok": False, "error": "Wrong name or password.", "data": None}, status_code=401)
    _failures.pop(name, None)
    token, _expires = await run_in_threadpool(start_session, workspace_path, person.person_id)
    log.info(f"✅ Admin signed in — {person.name}", sign_in=person.sign_in)
    response = JSONResponse({"ok": True, "error": None, "data": {"person": _public(person)}})
    response.set_cookie(
        cookie_name(request),
        token,
        max_age=SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="strict",
        secure=_over_https(request),
        path="/",
    )
    return response


@auth_router.post("/auth/sign-out")
async def sign_out(request: Request) -> JSONResponse:
    name = cookie_name(request)
    person = await signed_in_person(request)
    await run_in_threadpool(end_session, _workspace_path(request), request.cookies.get(name))
    if person is not None:
        log.info(f"Admin signed out — {person.name}", sign_in=person.sign_in)
    response = JSONResponse({"ok": True, "error": None, "data": None})
    response.delete_cookie(name, path="/")
    return response
