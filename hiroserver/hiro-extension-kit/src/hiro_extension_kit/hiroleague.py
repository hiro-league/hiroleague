"""HiroLeague: the app as an extension of the HiroLeague core (its name there: `Extension.name`, e.g. `net`).

The app connects to the core's extension socket with HiroLeague's SDK (`hiro_channel_sdk.ExtensionClient`): it pairs
once with a code from the core's admin (Extensions, Add an extension) and signs in on every connection with its own key,
kept in DATA_DIR/hiroleague (backed up with the rest of the app's data; lost: pair again). Then requests, responses and
events travel both ways: the family list and its rights (family.py), signing in (auth/api.py: `auth.code`), and what
each app asks or answers on top (its own modules use `link.client`).

The connection never holds the app up: with the core down or redeploying, the client retries with growing delays in
the background and nothing else waits on it.

Settings → HiroLeague sets the core's address (stored in the database, key `hiroleague_url`), the app's own address
(key `<app>_url`, e.g. `nethiro_url`) and pairs. The app's address is a LAN name the core sets up (`sites.claim`,
hiroleague docs/site-names-design.md): the app claims `<label>.hiro.local` or `<label>.local` with the port it listens on,
the core publishes the name and points its web proxy there, and the app then declares `http://<name>` as its site. Until
a name is set, the app claims `<Extension.name>.hiro.local` by itself once connected.

Backend kit, step 3: NetHiro's and TrainHiro's own copies, the same but for the values now in `Extension`.
"""

import time
from typing import Any

from hiro_channel_sdk import ExtensionClient, ExtensionCredentials, ExtensionInfo, ExtensionOffers, ExtensionRequestError
from hiro_channel_sdk.constants import (METHOD_CORE_INFO, METHOD_SITES_CLAIM, OFFER_KIND_SITE, SITES_DOMAIN, SITES_ERROR_INVALID,
                                        SITES_ERROR_TAKEN)
from hiro_channel_sdk.extension import STATUS_CONNECTED
from hiro_channel_sdk.workers import Worker
from sqlmodel import Session

from . import calls, identity, settings
from .db import run_db
from .errors import AppError, Invalid, OutsideError, Unavailable, failed, translate
from .events import bus
from .extension import ext
from .site_name import BadLabel, name_of, site_name

log = identity.logger("hiroleague")

URL_KEY = "hiroleague_url"
# The address people open the core's admin at (its Edit links), e.g. http://hiro.local behind Caddy; "" = the core's
# host (from URL_KEY) and the admin port it says when it connects (core.info's admin_port).
ADMIN_URL_KEY = "hiroleague_admin_url"
# The app's own address, the site it declares to the core (its Apps card opens it; the core sends people back only
# there after signing them in): `http://<the name the core set up>` (claim_site_name); "" = none claimed yet.
SITE_URL_KEY = f"{identity.app().name}_url"  # nethiro_url
DEFAULT_KIND = "subdomain"  # the name the app claims by itself while none is set: <Extension.name>.hiro.local
# A claim may reload the core's proxy (the core waits up to 60 s for it).
SITES_TIMEOUT = 75.0
HOME = "home"  # HomeHiro's name in the core
CONNECTED = "hiroleague connected"  # published on the bus each time the link is connected (signed in)
LOOPBACK = {"127.0.0.1", "localhost", "[::1]"}  # the core on the app's own machine


def _title() -> str:
    return identity.app().title


def site_url_default() -> str:
    """The address the app claims by itself while none is set: http://<Extension.name>.hiro.local."""
    return site_name(ext().name, DEFAULT_KIND).url


def info_for(site_url: str) -> ExtensionInfo:
    """What the app declares to the core: its questions, its site at `site_url` for every role, its AI uses and its
    features and rights. Built at connect time and again when the address changes (Settings → HiroLeague)."""
    e = ext()
    offers = ExtensionOffers(
        knows=list(e.knows),
        shows=[{"kind": OFFER_KIND_SITE, "title": e.site_title, "icon": e.site_icon, "url": site_url, "roles": []}],
    )
    return ExtensionInfo(name=e.name, version=e.version, description=e.description, offers=offers, uses=list(e.uses),
                         repo=e.repo,  # its repo: the code reports keep a report for it (HiroLeague's extensions.list)
                         features=list(e.features))  # its features and rights, granted per role in HiroLeague


def _read(session: Session, key: str) -> str:
    return settings.get(session, key) or ""


def _write(session: Session, key: str, value: str) -> None:
    settings.put(session, key, value or None)
    session.commit()


def check_admin_url(url: str) -> str:
    """The admin's address as typed, trimmed, without a trailing slash; refuses anything but http(s)://."""
    url = url.strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        raise Invalid("The admin's address starts with http:// (e.g. http://hiro.local).")
    return url


def derived_admin_url(ws_url: str, admin_port: Any) -> str:
    """http://<the core's host>:<admin port>, from the extension address and the port the core says; "" unknown."""
    if not ws_url or not isinstance(admin_port, int):
        return ""
    host = ws_url.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0]
    if host in LOOPBACK:
        # Phase 9b fix: the app reaches the core on the same machine (127.0.0.1), but people's browsers can't: the
        # core's admin is at its LAN name then (http://hiro.local, the core's Caddy); sign-in sent them nowhere
        return f"http://{SITES_DOMAIN}"
    return f"http://{host}:{admin_port}" if host else ""


def check_url(url: str) -> str:
    """The address as typed, trimmed; refuses anything that isn't ws:// or wss://."""
    url = url.strip()
    if url and not url.startswith(("ws://", "wss://")):
        raise Invalid("The core's address starts with ws:// (e.g. ws://127.0.0.1:18082).")
    return url


class SiteNameError(OutsideError):
    """Setting up the app's name through HiroLeague failed, didn't answer, or answered something the app can't read
    (502). Its refusals (the name is taken or can't be a name) are `Invalid` in the core's words."""


def _no_core_for_name() -> str:
    return f"{_title()} isn't connected to HiroLeague, so it can't set up the name (Settings → HiroLeague)."


def _claim_error(exc: ExtensionRequestError) -> Exception:
    """The core's no to sites.claim as the app's error."""
    if exc.code in (SITES_ERROR_TAKEN, SITES_ERROR_INVALID):  # the core's reason, written for people
        return Invalid(exc.message)
    if exc.code == "not_connected":  # the connection dropped on the way
        return Unavailable(_no_core_for_name())
    if exc.code == "timeout":
        return SiteNameError(f"HiroLeague didn't answer in {SITES_TIMEOUT:.0f} s; the name may be set up already. "
                             "Save again to be sure.")
    return SiteNameError(f"HiroLeague couldn't set up the name ({exc.code}): {exc.message}")


class HiroLeagueLink(Worker):
    """Keeps the app connected to the HiroLeague core. Made when this module loads (`link`); what it declares is read
    from the app's `Extension` when it connects, so the app's own modules may register their requests on `link.client`
    before it starts."""

    name = "hiroleague"

    def __init__(self) -> None:
        super().__init__()
        self.admin_url_set = ""  # Settings → HiroLeague's admin address ("" = derived); read when the link starts
        self.site_url_set = ""  # the app's address ("" = none claimed yet: the default); read when the link starts
        # (the real info is set at connect time, from the app's Extension: _connect)
        self.client = ExtensionClient("", ExtensionInfo(name=identity.app().name, version="0"),
                                      ExtensionCredentials(identity.app().data_dir / "hiroleague"), on_status=self._status)

    def _status(self, status: str, _detail: dict[str, Any]) -> None:
        # The SDK awaits this before it reads the connection's frames: never ask the core from here. The bus runs its
        # subscribers on the loop, so they start their requests on their own (family.py).
        if status == STATUS_CONNECTED:
            bus.publish(CONNECTED)
            if not self.site_url_set:  # no name yet: claim <name>.hiro.local (not awaited here, see above)
                self.spawn(self._claim_default(), "claim the default name")

    def on_start(self) -> None:
        # Stopping the worker cancels this task, which closes the connection.
        self.spawn(self._connect(), "connect")

    async def _connect(self) -> None:
        self.admin_url_set = await run_db(_read, ADMIN_URL_KEY)
        self.site_url_set = await run_db(_read, SITE_URL_KEY)
        self.client.update_info(info_for(self.site_url()))  # declared with the address set
        url = await run_db(_read, URL_KEY)
        self.client.set_url(url)
        await self.client.run()

    async def _claim_default(self) -> None:
        """The app's first connection claims <name>.hiro.local, so its Apps card and sign-in work without a visit to
        Settings. Refused or failed: logged, and tried again at the next connection."""
        try:
            await self.claim_site_name(ext().name, DEFAULT_KIND)
        except AppError as exc:
            failed(log, f"HiroLeague: claiming {_title()}'s default name {site_url_default()}", exc)

    # --- what Settings → HiroLeague reads and does ---

    def status(self) -> dict[str, Any]:
        detail = self.client.status_detail
        core = detail.get("core")
        return {
            "url": self.client.url,
            "status": self.client.status,
            "error": detail.get("error"),
            "core": core,
            "admin_url_set": self.admin_url_set,
            "admin_url": self.admin_url(),
            "site_url_set": self.site_url_set,
            "site_url": self.site_url(),
            **self._site_form(),
        }

    def _site_form(self) -> dict[str, Any]:
        """The address as the form shows it: its label and kind (None for an address that isn't one of the names)."""
        name = name_of(self.site_url())
        return {"site_label": name.label if name else None, "site_kind": name.kind if name else None}

    def site_url(self) -> str:
        """The app's address: the one set, else the default it claims."""
        return self.site_url_set or site_url_default()

    async def claim_site_name(self, label: str, kind: str) -> dict[str, Any]:
        """A new name for the app (`net` → net.hiro.local, or `abc` → abc.local), set up by the core: it publishes the
        name on the LAN and points its proxy at the app's port. Only when the core says yes is `http://<name>` saved
        and declared (the link reconnects, so the core reads the new info); a refusal saves nothing."""
        try:
            wanted = site_name(label, kind)
        except BadLabel as exc:
            raise Invalid(str(exc)) from exc
        if not self.client.connected:
            raise Unavailable(_no_core_for_name())
        started = calls.start()
        try:
            answer = await self.client.request(METHOD_SITES_CLAIM, {"name": wanted.name, "port": ext().port},
                                               timeout=SITES_TIMEOUT)
        except ExtensionRequestError as exc:
            raise _claim_error(exc) from exc
        calls.done(log, f"HiroLeague: {METHOD_SITES_CLAIM}", started, timeout=SITES_TIMEOUT)
        with translate(SiteNameError, "HiroLeague's answer about the name can't be read"):
            name = str(answer["name"])
            published, proxied = bool(answer["published"]), bool(answer["proxied"])
            note = str(answer.get("note") or "")
        url = f"http://{name}"
        await run_db(_write, SITE_URL_KEY, url)
        self.site_url_set = url
        self.client.update_info(info_for(self.site_url()))
        if self.client.url:
            self.client.set_url(self.client.url)  # the SDK's way to reconnect: the core reads the info at sign-in
        log.info("HiroLeague: %s's address is now %s (published: %s, proxied: %s)%s", _title(), url,
                 "yes" if published else "no", "yes" if proxied else "no", f"; {note}" if note else "")
        return {"name": name, "url": url, "published": published, "proxied": proxied, "note": note,
                "status": self.status()}

    def admin_url(self) -> str:
        """Where the core's admin opens (Edit links): the address set, else derived from the core's host and port."""
        core = self.client.status_detail.get("core") or {}
        return self.admin_url_set or derived_admin_url(self.client.url, core.get("admin_port"))

    async def set_admin_url(self, url: str) -> dict[str, Any]:
        url = check_admin_url(url)
        await run_db(_write, ADMIN_URL_KEY, url)
        self.admin_url_set = url
        return self.status()

    async def set_url(self, url: str) -> dict[str, Any]:
        url = check_url(url)
        await run_db(_write, URL_KEY, url)
        self.client.set_url(url)
        return self.status()

    def pair(self, code: str) -> dict[str, Any]:
        code = code.strip()
        if not code:
            raise Invalid("Type the pairing code from the core's admin (Extensions, Add an extension).")
        if not self.client.url:
            raise Invalid("Set the core's address first.")
        self.client.pair(code)
        return self.status()

    def forget(self) -> dict[str, Any]:
        self.client.forget()
        return self.status()

    async def test(self) -> dict[str, Any]:
        """The app's test call: ask the core its name and version."""
        started = time.perf_counter()
        try:
            core = await self.client.request(METHOD_CORE_INFO)
        except ExtensionRequestError as exc:
            raise Invalid(f"The core didn't answer: {exc.message}") from exc
        return {"core": core, "elapsed_ms": round((time.perf_counter() - started) * 1000)}


link = HiroLeagueLink()
