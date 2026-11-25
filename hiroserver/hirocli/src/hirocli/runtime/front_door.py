"""The one client for the front door: Caddy's admin API (docs/site-names-design.md).

The core only ever loads Caddy's whole configuration (``POST /load``, a Caddyfile): no file, no reload command. Caddy
keeps what it loaded in its own autosave and brings it back after a restart (``caddy run --resume``), so the front
door serves through every core restart and deploy. Where the API listens comes from the core's service
(``HIRO_FRONT_DOOR``, set by ``hiro service install``); a core without it, a dev core or one whose machine has no
front door yet, never touches any Caddy.
"""

from __future__ import annotations

import os
import time

import httpx
from hiro_commons.log import Logger

from ..domain.front_door import ENV_FRONT_DOOR, AdminAddress, FrontDoorAddressError, parse_admin

log = Logger.get("FRONT_DOOR")

LOAD_TIMEOUT_S = 15.0  # Caddy applies a load at once; it only waits for its old servers to let go of their ports
SLOW_S = 3.0
# Where the front door listens when not port 80 on every address (`bind:port`): an environment on the PC, where a
# person can't give the port away; never set on a real install.
ENV_FRONT_DOOR_LISTEN = "HIRO_FRONT_DOOR_LISTEN"


class FrontDoorError(RuntimeError):
    """Caddy didn't take the configuration; the message is for people (Caddy keeps what it had)."""


class FrontDoor:
    """Caddy's admin API, over its unix socket (Linux, Mac) or its loopback port (Windows)."""

    def __init__(self, admin: AdminAddress, *, http_port: int = 80, bind: str = "") -> None:
        self.admin = admin
        self.http_port = http_port
        self.bind = bind

    def _client(self) -> httpx.AsyncClient:
        transport = httpx.AsyncHTTPTransport(uds=self.admin.socket) if self.admin.socket else None
        return httpx.AsyncClient(base_url=self.admin.base_url, transport=transport, timeout=LOAD_TIMEOUT_S)

    async def load(self, caddyfile: str) -> None:
        """Make ``caddyfile`` Caddy's whole configuration; raises FrontDoorError with Caddy's reason."""
        started = time.monotonic()
        try:
            async with self._client() as client:
                response = await client.post("/load", content=caddyfile.encode("utf-8"),
                                             headers={"Content-Type": "text/caddyfile"})
        except httpx.HTTPError as exc:
            raise FrontDoorError(
                f"The front door (Caddy) isn't answering on {self.admin.caddy}: is its service running? "
                f"({type(exc).__name__})"
            ) from exc
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if response.status_code >= 300:
            raise FrontDoorError(f"The front door (Caddy) refused the names: {_reason(response)}")
        if elapsed_ms > SLOW_S * 1000:
            log.warning(f"⚠️ Front door — Caddy was slow to take the names: {elapsed_ms} ms", elapsed_ms=elapsed_ms)
        else:
            log.debug("Front door — Caddy took the names", elapsed_ms=elapsed_ms)


def _reason(response: httpx.Response) -> str:
    """Caddy's own words for a refusal (``{"error": "..."}``), cut short."""
    try:
        said = str(response.json().get("error") or "")
    except ValueError:
        said = response.text
    return (said.strip() or f"status {response.status_code}")[:400]


def from_environment() -> tuple[FrontDoor | None, str]:
    """The front door this core drives, from its service's environment; (None, why) when it drives none."""
    text = os.environ.get(ENV_FRONT_DOOR, "").strip()
    if not text:
        return None, ("This machine has no front door yet: `hiro service install` sets it up. The name is kept, and "
                      "proxied once it is.")
    try:
        admin = parse_admin(text)
    except FrontDoorAddressError as exc:
        return None, str(exc)
    port, bind = 80, ""
    listen = os.environ.get(ENV_FRONT_DOOR_LISTEN, "").strip()
    if listen:
        host, _, port_text = listen.rpartition(":")
        if port_text.isdigit():
            port, bind = int(port_text), host
    return FrontDoor(admin, http_port=port, bind=bind), ""
