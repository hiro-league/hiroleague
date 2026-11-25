"""People → Sign-in: the ways into HiroLeague (trust fixes, Nov 25). Name and password always work; "Sign in with Home
Assistant" is an option the owner adds: connect the core to Home Assistant, say who each Home Assistant login is in
the family list, then turn it on (domain/home_assistant_sign_in.py, services/home_assistant.py).

Owner only (route_rules.py). Like the sign-in itself, it is the hosting workspace's (the one this server runs), never
the workspace the admin is looking at.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from hiro_commons.log import Logger
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from hirocli.admin_svelte.result_payload import api_failure
from hirocli.domain import home_assistant_sign_in as ha_sign_in
from hirocli.domain.home_assistant_sign_in import HaSignInError
from hirocli.services import home_assistant
from hirocli.services.home_assistant import HomeAssistantError

log = Logger.get("ADMIN.SIGN_IN")

sign_in_ways_router = APIRouter()

PREFIX = "/sign-in/home-assistant"


class HaLoginOut(BaseModel):
    ha_user_id: str
    name: str
    login: str
    person_id: str  # who the owner linked it to; '' = nobody (it can't sign in)
    suggested_id: str  # who it seems to be by name: a suggestion, it signs nobody in


class HaSignInOut(BaseModel):
    address: str  # where the core reaches Home Assistant
    link_address: str  # where people's browsers log in; '' = the same
    token_set: bool
    enabled: bool
    connected: bool
    version: str
    checked_at: str
    logins: list[HaLoginOut]


class ConnectBody(BaseModel):
    address: str
    link_address: str = ""
    token: str = ""  # "" = the one kept (Test again), for the same address only


class EnabledBody(BaseModel):
    on: bool


class LinkBody(BaseModel):
    person_id: str  # "" = nobody


def _workspace(request: Request) -> Path:
    return Path(request.app.state.ctx.workspace_path)


def _state(workspace: Path) -> HaSignInOut:
    ha = ha_sign_in.read(workspace)
    return HaSignInOut(
        address=ha.address, link_address=ha.link_address, token_set=ha.token_set, enabled=ha.enabled, connected=ha.connected, version=ha.version,
        checked_at=ha.checked_at,
        logins=[HaLoginOut(**lg.__dict__) for lg in ha_sign_in.logins(workspace)],
    )


@sign_in_ways_router.get(PREFIX)
async def get_home_assistant_sign_in(request: Request) -> HaSignInOut:
    return await run_in_threadpool(_state, _workspace(request))


@sign_in_ways_router.put(f"{PREFIX}/connection")
async def connect_home_assistant(body: ConnectBody, request: Request) -> HaSignInOut:
    """Test the connection with the address and token given (or the token kept), and keep them when it works."""
    workspace = _workspace(request)
    address = body.address.strip().rstrip("/")
    link_address = body.link_address.strip().rstrip("/")
    if link_address and not link_address.startswith(("http://", "https://")):
        return api_failure("The address in browsers must start with http:// or https://.", 400)
    token = body.token.strip()
    if not token:
        # The token kept goes only to the address it was kept for: a new address needs it typed again
        kept = await run_in_threadpool(ha_sign_in.read, workspace)
        if kept.address != address:
            return api_failure("Type the access token again for a new address.", 400)
        token = await run_in_threadpool(ha_sign_in.token, workspace)
    if not address or not token:
        return api_failure("Type Home Assistant's address and an access token.", 400)
    try:
        version, found = await home_assistant.check(address, token)
        await run_in_threadpool(ha_sign_in.connected, workspace, address, link_address, token, version, found)
    except (HomeAssistantError, HaSignInError) as exc:
        log.warning("⚠️ Home Assistant not connected for sign-in", error=str(exc))
        return api_failure(str(exc), 502 if isinstance(exc, HomeAssistantError) else 400)
    log.info(f"✅ Home Assistant connected for sign-in — {version} · {len(found)} login(s)")
    return await run_in_threadpool(_state, workspace)


@sign_in_ways_router.delete(f"{PREFIX}/connection")
async def disconnect_home_assistant(request: Request) -> HaSignInOut:
    workspace = _workspace(request)
    await run_in_threadpool(ha_sign_in.disconnect, workspace)
    log.info("Home Assistant disconnected: signing in with it is off")
    return await run_in_threadpool(_state, workspace)


@sign_in_ways_router.put(f"{PREFIX}/enabled")
async def set_home_assistant_sign_in(body: EnabledBody, request: Request) -> HaSignInOut:
    workspace = _workspace(request)
    try:
        await run_in_threadpool(ha_sign_in.set_enabled, workspace, body.on)
    except HaSignInError as exc:
        return api_failure(str(exc), 400)
    log.info(f"Sign in with Home Assistant is {'on' if body.on else 'off'}")
    return await run_in_threadpool(_state, workspace)


@sign_in_ways_router.put(PREFIX + "/logins/{ha_user_id}")
async def link_home_assistant_login(ha_user_id: str, body: LinkBody, request: Request) -> HaSignInOut:
    workspace = _workspace(request)
    try:
        linked = await run_in_threadpool(ha_sign_in.link, workspace, ha_user_id, body.person_id.strip())
    except HaSignInError as exc:
        return api_failure(str(exc), 400)
    log.info(f"Home Assistant login linked — {linked.name} → {linked.person_id or 'nobody'}")
    return await run_in_threadpool(_state, workspace)
