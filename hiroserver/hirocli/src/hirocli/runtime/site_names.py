"""Apps' LAN names, set up by the core (docs/site-names-design.md).

An extension's address setting claims a name (``sites.claim {name, port}``). The core keeps the claim
(domain/site_names.py), publishes the name on the LAN with one ``avahi-publish -a -R <name> <ip>`` per name (an
ordinary user may: no sudo), writes every claimed name into the Caddy file it owns and runs the reload command. At
start it does the same for every kept claim. A machine that isn't set up (no ``site_names_ip`` in the workspace
config) keeps the claims and publishes nothing; the answer says so.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hiro_channel_sdk.constants import METHOD_SITES_CLAIM
from hiro_commons.log import Logger

from ..domain.site_names import (
    SiteName,
    SiteNameError,
    caddy_names,
    claim,
    list_claims,
    render_caddy,
)
from .request_handler import EXTENSIONS_ONLY, RequestContext, RequestRefused
from .whatsapp_for_extensions import sender_label

if TYPE_CHECKING:
    from .server_context import ServerContext

log = Logger.get("SITE_NAMES")

RESTART_PUBLISHER_S = 5.0  # an avahi-publish that ended (avahi restarted) is started again after this long
RELOAD_TIMEOUT_S = 60.0


class SiteNames:
    """Publishes each claimed name and keeps Caddy's file in step. One per running server."""

    def __init__(self, ctx: ServerContext) -> None:
        self._ctx = ctx
        self._publishers: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    # -- the machine's setup (workspace config) ----------------------------------------------

    @property
    def _cfg(self) -> Any:
        return self._ctx.config

    def _ip(self) -> str:
        return (self._cfg.site_names_ip or "").strip()

    def _caddy_file(self) -> Path | None:
        p = (self._cfg.site_names_caddy_file or "").strip()
        return Path(p).expanduser() if p else None

    def _caddy_main(self) -> Path | None:
        p = (self._cfg.site_names_caddy_main or "").strip()
        return Path(p).expanduser() if p else None

    def hand_written(self) -> set[str]:
        """Names Caddy's hand-written file serves: taken, never touched."""
        try:
            return caddy_names(self._caddy_main())
        except OSError as exc:
            log.warning("⚠️ Site names — couldn't read the hand-written Caddyfile", error=str(exc))
            return set()

    # -- lifecycle -----------------------------------------------------------------------------

    async def run(self) -> None:
        """Publish every kept claim and write Caddy's file, then keep the publishers alive until the server stops."""
        claims = await asyncio.to_thread(list_claims, Path(self._ctx.workspace_path))
        if self._ip():
            async with self._lock:
                await self._apply(claims)
            log.info(f"✅ Site names ready — {len(claims)} app name(s)", names=", ".join(c.name for c in claims))
        elif claims:
            log.info("Site names kept, not published — this machine isn't set up (hiro extension names)")
        try:
            await asyncio.Event().wait()
        finally:
            for task in self._publishers.values():
                task.cancel()
            await asyncio.gather(*self._publishers.values(), return_exceptions=True)
            self._publishers.clear()

    async def claim(self, extension_id: str, name: str, port: int) -> dict[str, Any]:
        """Give the extension its name, publish it and proxy it; raises SiteNameError."""
        async with self._lock:
            hand = self.hand_written()
            kept, old = await asyncio.to_thread(claim, Path(self._ctx.workspace_path), extension_id, name, port, hand)
            published = proxied = False
            note = ""
            if not self._ip():
                note = "This server isn't set up to publish names (hiro extension names); the name is kept for later."
            else:
                claims = await asyncio.to_thread(list_claims, Path(self._ctx.workspace_path))
                proxied, note = await self._apply(claims)
                published = kept.name in self._publishers
        if old:
            log.info(f"Site name dropped — {old} · replaced by {kept.name}", extension_id=extension_id)
        return {
            "name": kept.name,
            "url": f"http://{kept.name}",
            "published": published,
            "proxied": proxied,
            "note": note,
        }

    # -- applying ------------------------------------------------------------------------------

    async def _apply(self, claims: list[SiteName]) -> tuple[bool, str]:
        """Publish exactly these names and write them into Caddy's file; (Caddy reloaded, a note when not)."""
        wanted = {c.name for c in claims}
        for name in list(self._publishers):
            if name not in wanted:
                self._publishers.pop(name).cancel()
        if shutil.which("avahi-publish") is None:
            note = "avahi-publish isn't installed here, so names aren't published on the LAN."
            log.warning(f"⚠️ Site names — {note}")
        else:
            note = ""
            for name in wanted - set(self._publishers):
                self._publishers[name] = asyncio.create_task(self._publish(name), name=f"site-name:{name}")
        proxied, caddy_note = await self._write_caddy(claims)
        return proxied, " ".join(n for n in (note, caddy_note) if n)

    async def _publish(self, name: str) -> None:
        """Keep ``name`` published: avahi-publish runs as long as the name is claimed, restarted if it ends."""
        ip = self._ip()
        while True:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "avahi-publish", "-a", "-R", name, ip,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
            except OSError as exc:
                log.error(f"❌ Site name not published — {name}", error=str(exc))
                return
            log.info(f"⬆️ Site name published — {name} · {ip}")
            try:
                _, err = await proc.communicate()
            except asyncio.CancelledError:
                with contextlib.suppress(ProcessLookupError):
                    proc.terminate()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=5)
                log.info(f"Site name unpublished — {name}")
                raise
            log.warning(
                f"⚠️ Site name publisher ended — {name} · restarting in {RESTART_PUBLISHER_S:.0f}s",
                code=proc.returncode,
                error=(err or b"").decode(errors="replace").strip()[:300],
            )
            await asyncio.sleep(RESTART_PUBLISHER_S)

    async def _write_caddy(self, claims: list[SiteName]) -> tuple[bool, str]:
        target = self._caddy_file()
        if target is None:
            return False, "No Caddy file is set (hiro extension names), so the name isn't proxied."
        text = render_caddy(claims)
        try:
            current = target.read_text(encoding="utf-8") if target.is_file() else None
            if current != text:
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_suffix(target.suffix + ".tmp")
                tmp.write_text(text, encoding="utf-8")
                tmp.replace(target)
        except OSError as exc:
            log.error("❌ Site names — couldn't write the Caddy file", path=str(target), error=str(exc))
            return False, f"Couldn't write the Caddy file: {exc}"
        if current == text:
            return True, ""
        return await self._reload_caddy()

    async def _reload_caddy(self) -> tuple[bool, str]:
        command = [str(a) for a in (self._cfg.site_names_caddy_reload or []) if str(a)]
        if not command:
            return False, "No Caddy reload command is set (hiro extension names); Caddy reads the file at its next start."
        try:
            proc = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
            )
            _, err = await asyncio.wait_for(proc.communicate(), timeout=RELOAD_TIMEOUT_S)
        except (OSError, asyncio.TimeoutError) as exc:
            log.error("❌ Site names — Caddy reload failed", command=" ".join(command), error=str(exc))
            return False, f"Caddy didn't reload: {exc}"
        if proc.returncode != 0:
            detail = (err or b"").decode(errors="replace").strip()[:300]
            log.error("❌ Site names — Caddy reload failed", command=" ".join(command), error=detail)
            return False, f"Caddy didn't reload: {detail or proc.returncode}"
        log.info("✅ Site names — Caddy reloaded", command=" ".join(command))
        return True, ""


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
