"""The core's Home Assistant client, for "Sign in with Home Assistant" only (domain/home_assistant_sign_in.py).

- `check(address, token)`: the owner's connection test, with a long-lived access token from their HA profile: HA's
  version and the people who can log in (`person/list`, and `config/auth/list` for their login names when the token's
  user is an administrator; without it, the names are left blank).
- The login (HA's login for other apps, IndieAuth): the browser goes to HA's `/auth/authorize` with the core's own
  address as the client id; HA sends it back with a code; the core trades the code for the person's tokens
  (`/auth/token`), asks HA whose they are (`auth/current_user`, on a WebSocket opened with the person's own token),
  then hands the refresh token back (`/auth/revoke`), so no login is left in their HA profile. The core keeps its own
  session and never acts with the person's HA login.

It only reads Home Assistant: a test environment lets it through where HA is real or read only (its switchboard).
Every failure is a `HomeAssistantError` in words for people; messages name paths, never a code or a token.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
import websockets
from hiro_commons import switchboard
from hiro_commons.log import Logger
from websockets.exceptions import InvalidURI, WebSocketException

from ..domain.home_assistant_sign_in import HaLogin

log = Logger.get("SIGN_IN.HA")

TIMEOUT = 10.0  # seconds, each call


class HomeAssistantError(Exception):
    """Home Assistant couldn't be reached, refused, or answered something unreadable: said in words for people."""


def _gate() -> None:
    try:
        switchboard.check("ha")
    except switchboard.Refused as exc:
        raise HomeAssistantError(str(exc)) from exc


def _base(address: str) -> str:
    parts = urlsplit((address or "").strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise HomeAssistantError("Home Assistant's address must start with http:// or https://.")
    return f"{parts.scheme}://{parts.netloc}"


def _ws_url(address: str) -> str:
    base = _base(address)
    return ("wss://" + base[len("https://"):] if base.startswith("https://") else "ws://" + base[len("http://"):]) + "/api/websocket"


class _Session:
    """One WebSocket to HA, signed in with a token: `call(type, **params)` answers one command's result."""

    def __init__(self, ws: Any, version: str) -> None:
        self._ws = ws
        self.version = version
        self._next = 1

    async def call(self, kind: str, **params: Any) -> Any:
        self._next += 1
        await self._ws.send(json.dumps({"id": self._next, "type": kind, **params}))
        while True:
            answer = json.loads(await _recv(self._ws))
            if answer.get("id") == self._next and answer.get("type") == "result":
                break
        if not answer.get("success"):
            code = str((answer.get("error") or {}).get("code") or "failed")
            raise HomeAssistantError(f"{kind}: Home Assistant refused it ({code})")
        return answer.get("result")


@asynccontextmanager
async def _session(address: str, access_token: str) -> AsyncIterator[_Session]:
    _gate()
    started = time.monotonic()
    try:
        async with websockets.connect(_ws_url(address), open_timeout=TIMEOUT, close_timeout=2, max_size=None) as ws:
            first = json.loads(await _recv(ws))
            if first.get("type") != "auth_required":
                raise HomeAssistantError("That address answered, but not like Home Assistant.")
            await ws.send(json.dumps({"type": "auth", "access_token": access_token}))
            said = json.loads(await _recv(ws))
            if said.get("type") != "auth_ok":
                raise HomeAssistantError("Home Assistant didn't accept the access token.")
            log.debug("HA: signed in on the WebSocket", elapsed_ms=round((time.monotonic() - started) * 1000, 1))
            yield _Session(ws, str(said.get("ha_version") or ""))
    except HomeAssistantError:
        raise
    except (OSError, TimeoutError, InvalidURI, WebSocketException) as exc:
        raise HomeAssistantError(f"Home Assistant couldn't be reached at {_base(address)} ({type(exc).__name__}).") from exc
    except (ValueError, TypeError) as exc:  # json and shapes: an answer that can't be read
        raise HomeAssistantError("Home Assistant answered something the core can't read.") from exc


async def _recv(ws: Any) -> str:
    try:
        return await asyncio.wait_for(ws.recv(), TIMEOUT)
    except TimeoutError as exc:
        raise HomeAssistantError(f"No answer from Home Assistant within {TIMEOUT:.0f} s.") from exc


async def check(address: str, access_token: str) -> tuple[str, list[HaLogin]]:
    """The connection test: HA's version, and each HA person who can log in (a person with a user)."""
    async with _session(address, access_token) as ha:
        people = await ha.call("person/list")
        try:
            users = await ha.call("config/auth/list")  # administrators only: the login names
        except HomeAssistantError:
            users = []
    names = {str(u.get("id")): str(u.get("username") or "") for u in users or [] if isinstance(u, dict)}
    found = []
    for p in [*(people or {}).get("storage", []), *(people or {}).get("config", [])]:
        if isinstance(p, dict) and p.get("user_id"):
            uid = str(p["user_id"])
            found.append(HaLogin(ha_user_id=uid, name=str(p.get("name") or uid), login=names.get(uid, "")))
    log.info(f"✅ Home Assistant reached — {ha.version} · {len(found)} login(s)")
    return ha.version, found


def authorize_url(address: str, client_id: str, redirect_uri: str, state: str) -> str:
    """Where the browser logs in: HA's own login page."""
    query = urlencode({"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "state": state})
    return f"{_base(address)}/auth/authorize?{query}"


async def _post(address: str, path: str, form: dict[str, str]) -> httpx.Response:
    _gate()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            return await client.post(f"{_base(address)}{path}", data=form)
    except httpx.TimeoutException as exc:
        raise HomeAssistantError(f"{path}: no answer from Home Assistant within {TIMEOUT:.0f} s.") from exc
    except httpx.HTTPError as exc:
        raise HomeAssistantError(f"{path}: Home Assistant couldn't be reached ({type(exc).__name__}).") from exc


async def exchange_code(address: str, client_id: str, code: str) -> tuple[str, str]:
    """The person's tokens for the code HA gave the browser: (access token, refresh token)."""
    r = await _post(address, "/auth/token", {"grant_type": "authorization_code", "code": code, "client_id": client_id})
    if r.status_code in (400, 401, 403):
        raise HomeAssistantError("Home Assistant didn't accept the sign-in (it may have taken too long). Try again.")
    if r.status_code >= 400:
        raise HomeAssistantError(f"/auth/token: Home Assistant answered HTTP {r.status_code}.")
    try:
        data = r.json()
        return str(data["access_token"]), str(data.get("refresh_token") or "")
    except (ValueError, KeyError, TypeError) as exc:
        raise HomeAssistantError("/auth/token: an answer the core can't read.") from exc


async def current_user(address: str, access_token: str) -> tuple[str, str]:
    """Whose a token is: (HA user id, their name)."""
    async with _session(address, access_token) as ha:
        user = await ha.call("auth/current_user")
    if not isinstance(user, dict) or not user.get("id"):
        raise HomeAssistantError("auth/current_user: an answer the core can't read.")
    return str(user["id"]), str(user.get("name") or user["id"])


async def revoke(address: str, refresh_token: str) -> None:
    """Hand the refresh token back: the sign-in leaves no login behind in the person's HA profile."""
    r = await _post(address, "/auth/revoke", {"token": refresh_token})
    if r.status_code >= 400:
        raise HomeAssistantError(f"/auth/revoke: Home Assistant answered HTTP {r.status_code}.")
