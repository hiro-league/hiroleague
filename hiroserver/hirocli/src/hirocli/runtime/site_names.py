"""Every name on the LAN, served by the core (docs/site-names-design.md): announced, and loaded into the front door.

An app's address setting claims its main name (``sites.claim {name, port}``); the owner adds extra names and other
sites (``hiro sites``); the core serves its own two (``hiro.local``, the gateway's). At start, and on every change
(a claim, a removed app, ``hiro sites``), the core:

- announces each served name on the LAN (runtime/name_publisher.py: avahi on Linux, zeroconf on Windows and Mac), on
  a machine set up for it (``site_names_ip``, ``hiro extension names``);
- loads the front door's whole configuration through Caddy's admin API (runtime/front_door.py), when this core runs
  the machine's front door (``HIRO_FRONT_DOOR``, set by ``hiro service install``). A load Caddy refuses leaves it
  serving what it had; the core tries again until it takes one.

A machine with neither keeps the claims, and the claim's answer says so.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hiro_channel_sdk.constants import METHOD_SITES_CLAIM
from hiro_commons.log import Logger

from ..domain.events import DomainEvent, DomainEventType, get_domain_event_bus
from ..domain.front_door import render
from ..domain.site_names import (
    Site,
    SiteNameError,
    claim,
    core_names,
    list_claims,
    list_other_sites,
    served,
    taken_by_core,
)
from .front_door import FrontDoor, FrontDoorError, from_environment
from .name_publisher import NamePublisher, make_publisher
from .request_handler import EXTENSIONS_ONLY, RequestContext, RequestRefused
from .whatsapp_for_extensions import sender_label

if TYPE_CHECKING:
    from .server_context import ServerContext

log = Logger.get("SITE_NAMES")

RETRY_LOAD_S = 30.0  # a load Caddy refused (or Caddy away) is tried again this often


class SiteNames:
    """Announces every served name and keeps the front door in step. One per running server."""

    def __init__(self, ctx: ServerContext, *, front_door: FrontDoor | None = None, door_note: str = "") -> None:
        self._ctx = ctx
        if front_door is None and not door_note:
            front_door, door_note = from_environment()
        self._door = front_door
        self._door_note = door_note
        self._publisher: NamePublisher | None = None
        self._lock = asyncio.Lock()
        self._loaded = ""  # the configuration Caddy took last
        self._door_failed = ""  # why the last load failed (said once, and once more when it works again)
        self._clashes: frozenset[str] = frozenset()

    # -- the machine's setup -------------------------------------------------------------------

    @property
    def _cfg(self) -> Any:
        return self._ctx.config

    def _ip(self) -> str:
        return (self._cfg.site_names_ip or "").strip()

    def _core_names(self) -> list[Any]:
        cfg = self._cfg
        return core_names(admin_port=cfg.admin_port, gateway_url=cfg.gateway_url, gateway_port=cfg.gateway_port,
                          gateway_builtin=cfg.gateway_builtin)

    def taken(self) -> set[str]:
        """What no app or site may take: the core's own names. The tables refuse the rest."""
        return taken_by_core(self._cfg)

    def _publisher_for_ip(self) -> NamePublisher | None:
        ip = self._ip()
        if not ip:
            return None
        if self._publisher is None or getattr(self._publisher, "ip", ip) != ip:
            self._publisher = make_publisher(ip)
        return self._publisher

    # -- lifecycle -----------------------------------------------------------------------------

    async def run(self) -> None:
        """Serve every name, then follow each change and try a refused load again, until the server stops."""
        bus = get_domain_event_bus()
        bus.subscribe(DomainEventType.EXTENSION_REMOVED, self._on_change)
        bus.subscribe(DomainEventType.SITES_CHANGED, self._on_change)
        try:
            async with self._lock:
                sites, _ = await self._apply()
            names = ", ".join(s.name for s in sites)
            if self._ip() or self._door:
                log.info(f"✅ Site names ready — {len(sites)} name(s)", names=names,
                         announced=bool(self._ip()), front_door=self._door.admin.caddy if self._door else "")
            elif sites:
                log.info("Site names kept, not served — this machine isn't set up (hiro extension names, "
                         "hiro service install)", names=names)
            while True:
                await asyncio.sleep(RETRY_LOAD_S)
                if self._door_failed:
                    await self._retry()
        finally:
            bus.unsubscribe(DomainEventType.EXTENSION_REMOVED, self._on_change)
            bus.unsubscribe(DomainEventType.SITES_CHANGED, self._on_change)
            if self._publisher is not None:
                await self._publisher.close()

    async def _retry(self) -> None:
        """One round of trying the front door again: a round that fails is logged, and the next one comes."""
        try:
            async with self._lock:
                await self._apply()
        except Exception:  # noqa: BLE001 — the loop must outlive one bad round (backend §1.3); logged with its traceback
            log.error("❌ Site names — a round of serving the names failed; the next one is in "
                      f"{RETRY_LOAD_S:.0f}s", exc_info=True)

    async def claim(self, extension_id: str, name: str, port: int) -> dict[str, Any]:
        """Give the extension its main name, announce it and proxy it; raises SiteNameError."""
        async with self._lock:
            kept, old = await asyncio.to_thread(claim, Path(self._ctx.workspace_path), extension_id, name, port,
                                                self.taken())
            _, (proxied, note) = await self._apply()
        if old:
            log.info(f"Site name dropped — {old} · replaced by {kept.name}", extension_id=extension_id)
        publisher = self._publisher if self._ip() else None
        published = publisher is not None and kept.name in publisher.announced
        if publisher is None:
            note = " ".join(n for n in ("This server isn't set up to announce names (hiro extension names); the "
                                        "name is kept for later.", note) if n)
        elif publisher.note:
            note = " ".join(n for n in (publisher.note, note) if n)
        return {"name": kept.name, "url": f"http://{kept.name}", "published": published, "proxied": proxied,
                "note": note}

    async def _on_change(self, event: DomainEvent) -> None:
        """A name changed elsewhere (an app removed, ``hiro sites``): serve what the tables hold now."""
        if not _same_place(event.workspace_path, self._ctx.workspace_path):
            return
        async with self._lock:
            await self._apply()
        if event.type == DomainEventType.EXTENSION_REMOVED and event.payload.get("site_name"):
            log.info(f"Site name gone with its app — {event.payload['site_name']} · {event.payload.get('name') or '?'}")

    # -- serving -------------------------------------------------------------------------------

    async def _apply(self) -> tuple[list[Site], tuple[bool, str]]:
        """Announce exactly the served names and load them into the front door; (the sites, (proxied, note))."""
        workspace = Path(self._ctx.workspace_path)
        claims = await asyncio.to_thread(list_claims, workspace)
        others = await asyncio.to_thread(list_other_sites, workspace)
        plan = served(claims, self._core_names(), others)
        self._say_clashes(plan.clashes)
        publisher = self._publisher_for_ip()
        if publisher is not None:
            await publisher.sync({s.name for s in plan.sites if s.announce})
        return plan.sites, await self._load(plan.sites)

    async def _load(self, sites: list[Site]) -> tuple[bool, str]:
        """Load the front door's whole configuration when it changed; (Caddy has it, a note when not)."""
        if self._door is None:
            return False, self._door_note
        text = render(sites, self._door.admin, http_port=self._door.http_port, bind=self._door.bind)
        if text == self._loaded:
            return True, ""
        try:
            await self._door.load(text)
        except FrontDoorError as exc:
            reason = str(exc)
            if reason != self._door_failed:
                log.warning(f"⚠️ Front door — Caddy kept what it had; trying again every {RETRY_LOAD_S:.0f}s",
                            error=reason)
            self._door_failed = reason
            return False, reason
        if self._door_failed:
            log.info("✅ Front door — Caddy took the names again")
        self._door_failed = ""
        self._loaded = text
        proxied = sum(1 for s in sites if s.upstream)
        log.info(f"✅ Front door loaded — {proxied} name(s) proxied", names=", ".join(s.name for s in sites if s.upstream))
        return True, ""

    def _say_clashes(self, clashes: frozenset[str]) -> None:
        """Say once which of the core's names an app holds, and when the core takes one back."""
        for name in sorted(clashes - self._clashes):
            log.warning(f"⚠️ Site names — {name} is the core's, but an app claimed it first; the app keeps it")
        for name in sorted(self._clashes - clashes):
            log.info(f"✅ Site names — the core serves {name} now")
        self._clashes = clashes


def _same_place(a: object, b: object) -> bool:
    try:
        return Path(str(a)).resolve() == Path(str(b)).resolve()
    except OSError:
        return str(a) == str(b)


# ---------------------------------------------------------------------------
# sites.claim (extension → core)
# ---------------------------------------------------------------------------


async def handle_sites_claim(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    names: SiteNames | None = getattr(ctx.server_ctx, "site_names", None)
    if names is None:
        raise RequestRefused("invalid", "This HiroLeague can't set up app names.")
    extension_id = getattr(getattr(ctx.msg, "routing", None), "sender_id", "") or ""
    try:
        answer = await names.claim(extension_id, str(params.get("name") or ""), params.get("port"))
    except SiteNameError as exc:
        log.info(f"Site name refused — {sender_label(ctx)} · {exc.code}", name=params.get("name"))
        raise RequestRefused(exc.code, str(exc)) from exc
    log.info(f"✅ Site name claimed — {answer['name']} · {sender_label(ctx)}", port=params.get("port"),
             published=answer["published"], proxied=answer["proxied"])
    return answer


SITE_NAMES_REQUEST_HANDLERS: tuple[tuple[str, Any, frozenset[str]], ...] = (
    (METHOD_SITES_CLAIM, handle_sites_claim, EXTENSIONS_ONLY),
)
