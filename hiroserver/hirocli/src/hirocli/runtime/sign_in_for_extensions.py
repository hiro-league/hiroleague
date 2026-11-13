"""One sign-in for HiroLeague and its extensions' own sites (the plan's Phase 8).

An extension's site (HomeHiro at http://homehiro.local) sends a signed-out browser to the core's
sign-in page. Once the browser is signed in here, the core sends it back to the site the extension
declared, with a one-time code; the extension redeems the code over its paired connection
(``auth.code``) and keeps its own sign-in. Contract: hiro_channel_sdk.constants (Phase 8 block) and
docs/phase8-one-sign-in-design.md.

An extension may also offer a way to sign in (HomeHiro: Home Assistant's login). The core shows the
button and asks the extension to start (``sign_in.start``) and finish (``sign_in.finish``) it; the
extension answers which person signed in. The core keeps nothing about how they did.

What lives here: the one-time codes (memory only: they last a minute and die with the process), the
``auth.code`` handler, and reading what extensions declare (their sites and offered sign-ins).
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode, urlsplit

from hiro_channel_sdk.constants import (
    AUTH_CODE_SECONDS,
    AUTH_ERROR_INVALID_CODE,
    METHOD_AUTH_CODE,
    METHOD_SITES_LIST,
    OFFER_KIND_SIGN_IN,
    OFFER_KIND_SITE,
)
from hiro_commons.log import Logger

from ..domain.extensions import list_paired_extensions
from ..domain.people import get_person, get_role
from .request_handler import EXTENSIONS_ONLY, RequestContext, RequestRefused
from .whatsapp_for_extensions import sender_label

if TYPE_CHECKING:
    from .extension_manager import ExtensionManager

log = Logger.get("SIGN_IN")

# A sign-in started with an extension's offered way (Home Assistant's login page) must come back
# within this long.
SIGN_IN_STATE_SECONDS = 600


# ---------------------------------------------------------------------------
# What extensions declare
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Site:
    """An extension's own site (offers.shows, kind "site"): the Apps card's tile, and where to send people back."""

    extension_id: str
    extension: str  # the extension's name (HomeHiro: "home"), as ?for= names it
    title: str
    icon: str
    url: str  # its origin, e.g. http://homehiro.local
    roles: tuple[str, ...]  # () = every role
    online: bool


@dataclass(frozen=True)
class SignInOffer:
    """A way to sign in that a connected extension offers (offers.can_do, kind "sign_in")."""

    extension_id: str
    extension: str
    id: str  # e.g. "home_assistant"
    label: str  # e.g. "Home Assistant"


def origin_of(url: str) -> str | None:
    """``scheme://host[:port]`` of an http(s) address, or None when it isn't one."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def _offers(info: dict[str, Any], slot: str, kind: str) -> list[dict[str, Any]]:
    offers = info.get("offers") if isinstance(info, dict) else None
    items = offers.get(slot) if isinstance(offers, dict) else None
    return [i for i in items or [] if isinstance(i, dict) and i.get("kind") == kind]


def _site_from(extension_id: str, info: dict[str, Any], online: bool) -> Site | None:
    for item in _offers(info, "shows", OFFER_KIND_SITE):
        url = origin_of(str(item.get("url") or ""))
        if url is None:
            continue
        roles = tuple(str(r) for r in item.get("roles") or [] if r)
        return Site(
            extension_id=extension_id,
            extension=str(info.get("name") or ""),
            title=str(item.get("title") or info.get("name") or "App"),
            icon=str(item.get("icon") or ""),
            url=url,
            roles=roles,
            online=online,
        )
    return None


def list_sites(manager: ExtensionManager | None, workspace_path: Path) -> list[Site]:
    """Every paired extension's declared site: live info when connected, else what it last declared."""
    live = manager.snapshot() if manager is not None else {}
    sites: list[Site] = []
    seen: set[str] = set()
    for eid, conn in live.items():
        site = _site_from(eid, conn.get("info") or {}, online=True)
        if site is not None:
            sites.append(site)
            seen.add(eid)
    for paired in list_paired_extensions(workspace_path):
        if paired.extension_id in seen:
            continue
        site = _site_from(paired.extension_id, paired.info or {}, online=False)
        if site is not None:
            sites.append(site)
    return sites


def sites_for_role(sites: list[Site], role_id: str) -> list[Site]:
    return [s for s in sites if not s.roles or role_id in s.roles]


def find_site(manager: ExtensionManager | None, workspace_path: Path, extension: str) -> Site | None:
    """The site of the extension ?for= names (its name, or its id)."""
    for site in list_sites(manager, workspace_path):
        if extension in (site.extension, site.extension_id):
            return site
    return None


def list_sign_in_offers(manager: ExtensionManager | None) -> list[SignInOffer]:
    """The ways to sign in that connected extensions offer (shown only while they're connected)."""
    if manager is None:
        return []
    offers: list[SignInOffer] = []
    for eid, conn in manager.snapshot().items():
        info = conn.get("info") or {}
        for item in _offers(info, "can_do", OFFER_KIND_SIGN_IN):
            offer_id = str(item.get("id") or "").strip()
            if offer_id:
                offers.append(
                    SignInOffer(
                        extension_id=eid,
                        extension=str(info.get("name") or conn.get("name") or eid),
                        id=offer_id,
                        label=str(item.get("label") or offer_id),
                    )
                )
    return offers


def back_url(site: Site, code: str, next_path: str) -> str:
    """Where the browser goes back to: the extension's own route that redeems the code."""
    return f"{site.url}/api/auth/hiro?{urlencode({'code': code, 'next': local_path(next_path)})}"


def local_path(path: str | None) -> str:
    """Only a path on the same site, never another one ("//evil.example", "https://…")."""
    path = path or "/"
    return path if path.startswith("/") and not path.startswith(("//", "/\\")) else "/"


# ---------------------------------------------------------------------------
# One-time codes
# ---------------------------------------------------------------------------


@dataclass
class _Code:
    extension_id: str
    person_id: str
    expires: float


@dataclass
class _Started:
    """A sign-in started with an extension's offered way, waiting for the browser to come back."""

    extension_id: str
    method: str
    for_extension: str  # ?for= of the sign-in page ("" = the admin itself)
    next_path: str
    expires: float


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SignInCodes:
    """One-time codes for extensions, and started offered sign-ins. Memory only: both last minutes."""

    def __init__(self) -> None:
        self._codes: dict[str, _Code] = {}
        self._started: dict[str, _Started] = {}

    def _prune(self, now: float) -> None:
        self._codes = {k: c for k, c in self._codes.items() if c.expires > now}
        self._started = {k: s for k, s in self._started.items() if s.expires > now}

    def make_code(self, extension_id: str, person_id: str) -> str:
        now = time.monotonic()
        self._prune(now)
        code = secrets.token_urlsafe(32)
        self._codes[_hash(code)] = _Code(extension_id, person_id, now + AUTH_CODE_SECONDS)
        return code

    def redeem(self, code: str, extension_id: str) -> str | None:
        """The person a code signs in, once, for the extension it was made for; else None."""
        now = time.monotonic()
        self._prune(now)
        found = self._codes.get(_hash(code or ""))
        if found is None or found.extension_id != extension_id:
            return None
        del self._codes[_hash(code)]
        return found.person_id

    def start(self, extension_id: str, method: str, for_extension: str, next_path: str) -> str:
        now = time.monotonic()
        self._prune(now)
        state = secrets.token_urlsafe(24)
        self._started[state] = _Started(extension_id, method, for_extension, next_path, now + SIGN_IN_STATE_SECONDS)
        return state

    def finish(self, state: str) -> _Started | None:
        """The started sign-in this state belongs to, once; else None (unknown, used or too old)."""
        self._prune(time.monotonic())
        return self._started.pop(state or "", None)


CODES = SignInCodes()


# ---------------------------------------------------------------------------
# auth.code (extension → core)
# ---------------------------------------------------------------------------


async def handle_auth_code(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    """An extension redeems the code the core sent its site: who signed in."""
    extension_id = getattr(getattr(ctx.msg, "routing", None), "sender_id", "") or ""
    person_id = CODES.redeem(str(params.get("code") or ""), extension_id)
    if person_id is None:
        log.warning(f"⚠️ Sign-in code refused — {sender_label(ctx)} · unknown, used or too old")
        raise RequestRefused(AUTH_ERROR_INVALID_CODE, "That sign-in has expired. Sign in again.")
    workspace_path = Path(ctx.server_ctx.workspace_path)
    person = await asyncio.to_thread(get_person, workspace_path, person_id)
    if person is None:
        raise RequestRefused(AUTH_ERROR_INVALID_CODE, "That person is no longer in the family list.")
    role = await asyncio.to_thread(get_role, workspace_path, person.role_id)
    log.info(f"✅ Signed in through HiroLeague — {person.name} · {sender_label(ctx)}", role=person.role_id)
    return {
        "person_id": person.person_id,
        "name": person.name,
        "role_id": person.role_id,
        "role_name": role.name if role else person.role_id,
    }


# ---------------------------------------------------------------------------
# sites.list (extension → core): the app switcher
# ---------------------------------------------------------------------------


def app_entry(site: Site) -> dict[str, Any]:
    """One app as the Apps card and the app switcher show it."""
    return {"extension": site.extension, "title": site.title, "icon": site.icon, "url": site.url, "online": site.online}


async def handle_sites_list(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    """The apps one person may open, for an app's app switcher: the sites their role sees, and whether their role
    opens HiroLeague's settings (the app then shows HiroLeague too)."""
    workspace_path = Path(ctx.server_ctx.workspace_path)
    person_id = str(params.get("person_id") or "")
    person = await asyncio.to_thread(get_person, workspace_path, person_id) if person_id else None
    if person is None:
        return {"apps": [], "opens_settings": False}
    sites = await asyncio.to_thread(list_sites, ctx.server_ctx.extension_manager, workspace_path)
    role = await asyncio.to_thread(get_role, workspace_path, person.role_id)
    return {
        "apps": [app_entry(s) for s in sites_for_role(sites, person.role_id)],
        "opens_settings": bool(role and role.admin),
    }


SIGN_IN_REQUEST_HANDLERS: tuple[tuple[str, Any, frozenset[str]], ...] = (
    (METHOD_AUTH_CODE, handle_auth_code, EXTENSIONS_ONLY),
    (METHOD_SITES_LIST, handle_sites_list, EXTENSIONS_ONLY),  # the app switcher in every app
)
