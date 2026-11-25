"""HiroLeague: the app as an extension of the HiroLeague core (its name there: `Extension.name`, e.g. `net`).

The app connects to the core's extension socket with HiroLeague's SDK (`hiro_channel_sdk.ExtensionClient`): it pairs
once with a code from the core's admin (Extensions, Add an extension) and signs in on every connection with its own key,
kept in DATA_DIR/hiroleague (backed up with the rest of the app's data; lost: pair again). Then requests, responses and
events travel both ways: the family list and its rights (family.py), signing in (auth/api.py: `auth.code`), and what
each app asks or answers on top (its own modules use `link.client`).

The connection never holds the app up: with the core down or redeploying, the client retries with growing delays in
the background and nothing else waits on it.

While connected, the app's log lines (INFO and up) go to the core's log store too (the SDK's `log_sender`, started
with the link): the core's log tools then answer across every app. The app's own file stays the first copy.

Settings → HiroLeague sets the core's address (key `hiroleague_url`), the app's own address (key `<app>_url`, e.g.
`nethiro_url`) and pairs. The keys live in the app's database (`settings`), or in a store the app hands the link
(`LinkSettings`, `link.use_settings`): CodeHiro, which keeps its own SQLite store, not the kit's database. The app's
address is a LAN name the core sets up (`sites.claim`, hiroleague docs/site-names-design.md): the app claims
`<label>.hiro.local` or `<label>.local` with the port it listens on, the core publishes the name and points its web
proxy there, and the app then declares `http://<name>` as its site. Until a name is set, the app claims
`<Extension.name>.hiro.local` by itself once connected.

What the owner approved the app for (Permissions phase 8) comes with the core's welcome and with each
`approval.changed`: the link keeps it (`link.approval`, `link.approved_for`), and Settings → HiroLeague lists what still
waits for the owner. What the app asks for is its declaration's `asks` (`info_for`).

Backend kit, step 3: NetHiro's and TrainHiro's own copies, the same but for the values now in `Extension`.
"""

import asyncio
import time
from collections.abc import Callable
from typing import Any, Protocol

from hiro_channel_sdk import ExtensionClient, ExtensionCredentials, ExtensionInfo, ExtensionOffers, ExtensionRequestError
from hiro_channel_sdk.approvals import (AI_SEARCH, AI_USE, EVENT_APPROVAL_CHANGED, PARAM_SIGNED_IN, VOICE_SPEAK, WORDS,
                                        AppAsk, Approval)
from hiro_channel_sdk.constants import (CORE_REPO, EVENT_TYPE_RESOURCE_CHANGED, METHOD_CORE_INFO, METHOD_SITES_CLAIM,
                                        METHOD_SITES_LIST, OFFER_KIND_SITE, SITES_DOMAIN, SITES_ERROR_INVALID,
                                        SITES_ERROR_TAKEN)
from hiro_channel_sdk.extension import STATUS_CONNECTED
from hiro_channel_sdk.log_sender import LogSender
from hiro_channel_sdk.workers import Worker
from hiro_commons import logging_foundation
from sqlmodel import Session

from . import calls, identity, settings
from .auth.identity import DEV
from .errors import AppError, Invalid, OutsideError, Unavailable, failed, refusal, translate
from .events import bus
from .extension import ext
from .follow import Follower, Refresh
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
APPS_TIMEOUT = 5.0  # the app switcher's list of apps (sites.list): someone is waiting with the grid open
APPS_ASK_TIMEOUT = 15.0  # an ask to another app (extensions.ask), as the SDK's own default
CORE_NAME = CORE_REPO  # "hiroleague": the core's tile in the app switcher (its icon is the core's own logo)
HOME = "home"  # HomeHiro's name in the core
CONNECTED = "hiroleague connected"  # published on the bus each time the link is connected (signed in)
LOOPBACK = {"127.0.0.1", "localhost", "[::1]"}  # the core on the app's own machine


def _title() -> str:
    return identity.app().title


def site_url_default() -> str:
    """The app's address while none is set: `Extension.site_default` (HomeHiro's http://homehiro.local), else the name
    it claims by itself, http://<Extension.name>.hiro.local."""
    return ext().site_default or site_name(ext().name, DEFAULT_KIND).url


def _derived(uses: Any, permission: str, words: str) -> AppAsk:
    """An ask the kit adds for the uses the app declares, why from their names ("Its AI uses: Sorting sites")."""
    return AppAsk(permission=permission, why=f"{words}: {', '.join(u.name for u in uses)}")


def asks_for() -> list[AppAsk] | None:
    """What the app asks to do on its own (Permissions phase 8): its `Extension.asks`, and those its declared uses
    need that it didn't list (ai.use for AI uses, voice.speak for voice uses, ai.search for embed or rerank uses).
    None while the app sets none, so the core changes nothing for an app not updated yet."""
    e = ext()
    if e.asks is None:
        return None
    asks = list(e.asks)
    listed = {a.permission for a in asks}
    derived = [(AI_USE, e.uses, "Its AI uses"), (VOICE_SPEAK, e.voice_uses, "Its voice uses"),
               (AI_SEARCH, [*e.embed_uses, *e.rerank_uses], "Its search uses")]
    asks += [_derived(uses, permission, words) for permission, uses, words in derived if uses and permission not in listed]
    return asks


def info_for(site_url: str) -> ExtensionInfo:
    """What the app declares to the core: its questions, its site at `site_url` for every role, its AI uses, its
    features and rights, and what it asks to do on its own. Built at connect time and again when the address changes
    (Settings → HiroLeague)."""
    e = ext()
    offers = ExtensionOffers(
        knows=list(e.knows),
        can_do=list(e.can_do),
        tells=list(e.tells),
        shows=[{"kind": OFFER_KIND_SITE, "title": e.site_title, "icon": e.site_icon, "url": site_url,
                "roles": list(e.site_roles)}],
    )
    return ExtensionInfo(name=e.name, version=e.version, description=e.description, offers=offers, uses=list(e.uses), voice_uses=list(e.voice_uses),
                         embed_uses=list(e.embed_uses), rerank_uses=list(e.rerank_uses),
                         repo=e.repo,  # its repo: CodeHiro keeps a report for it (HiroLeague's extensions.list)
                         features=list(e.features),  # its features and rights, granted per role in HiroLeague
                         areas=dict(e.areas),  # the areas that group them (Permissions phase 6)
                         asks=asks_for())  # what it asks to do on its own (Permissions phase 8)


def as_person(params: dict[str, Any], signed_in: str | None) -> dict[str, Any]:
    """An ask made for a person signed in to the app (Permissions phase 8): `params` with their proof, the token the
    core gave at sign-in (`request.state.core_token`), which the core answers by their own rights. Always passed by the
    caller, never read from the request's context, so work a page starts and that runs on never carries it. None (sign-in
    off): sent without, and a test environment's core answers for its stand-in person."""
    return {**params, PARAM_SIGNED_IN: signed_in} if signed_in else params


def core_token(request: Any) -> str | None:
    """The proof of the person signed in, for what a route asks the core for them (Permissions phase 8: family's
    update_person, core_ai's set_use, voices' set_default, whatsapp's check), as the kit's sign-in keeps it on
    `request.state.core_token` (auth/api.py `caller`): None with sign-in off, through the app's other way in, or in an
    app with sign-in of its own. Passed on by hand (`as_person`), never kept in a context variable, so work a page starts
    that runs on after the answer never acts for the person."""
    return getattr(request.state, "core_token", None)


def covers(approval: Approval | None, permission: str, subject: str = "") -> bool:
    """Whether an approval lets the app do this on its own: True while the core said nothing, or approved everything (an
    app paired before approvals). For a page to show what can't work yet; the core decides. Pure."""
    if approval is None or approval.approved is None:
        return True
    return any(i.permission == permission and i.subject == subject for i in approval.approved)


def waiting_items(approval: Approval | None) -> list[dict[str, str]]:
    """What waits for the owner's approval in HiroLeague, in words (Settings → HiroLeague): pure."""
    if approval is None:
        return []
    return [{"permission": i.permission, "subject": i.subject, "words": WORDS.get(i.permission, i.permission)}
            for i in approval.waiting]


class LinkSettings(Protocol):
    """Where the link keeps what Settings → HiroLeague sets: the core's address (URL_KEY), the admin's (ADMIN_URL_KEY)
    and the app's own (SITE_URL_KEY). Plain functions, run in a worker thread since they may wait on a database;
    `put(key, "")` takes the key away (back to its default)."""

    def get(self, key: str) -> str: ...

    def put(self, key: str, value: str) -> None: ...


class AppDatabase:
    """The link's settings in the app's own database (`settings`, the kit's `db`): every app on the kit's database.
    `db` is imported on first use, so an app that hands the link a store of its own never opens the kit's database."""

    def get(self, key: str) -> str:
        from .db import engine  # first use: see the class's notes

        with Session(engine) as session:
            return settings.get(session, key) or ""

    def put(self, key: str, value: str) -> None:
        from .db import engine

        with Session(engine) as session:
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


class AppsListError(OutsideError):
    """HiroLeague couldn't list a person's apps (the app switcher), or answered something the app can't read (502)."""


def _no_core_for_name() -> str:
    return f"{_title()} isn't connected to HiroLeague, so it can't set up the name (Settings → HiroLeague)."


def _claim_error(exc: ExtensionRequestError) -> Exception:
    """The core's no to sites.claim as the app's error."""
    if (refused := refusal(exc)) is not None:  # not approved for that name yet: the core's words say where
        return refused
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
        self.settings: LinkSettings = AppDatabase()  # where its settings live (use_settings for another store)
        self.admin_url_set = ""  # Settings → HiroLeague's admin address ("" = derived); read when the link starts
        self.site_url_set = ""  # the app's address ("" = none claimed yet: the default); read when the link starts
        # (the real info is set at connect time, from the app's Extension: _connect)
        self.client = ExtensionClient("", ExtensionInfo(name=identity.app().name, version="0"),
                                      ExtensionCredentials(identity.app().data_dir / "hiroleague"), on_status=self._status)
        # The app's copies of what the core keeps (family, AI and voice profiles), kept fresh in one place (follow.py)
        self.follower = Follower(lambda: self.client.connected, log)
        self.client.on_event(EVENT_TYPE_RESOURCE_CHANGED, self.follower.changed)
        # What the owner approved it for and what waits (Permissions phase 8): None until the core says (a core from
        # before approvals never does). Kept across a dropped connection: it is still what the core last said.
        self.approval: Approval | None = None
        self.client.on_event(EVENT_APPROVAL_CHANGED, self._approval_changed)

    def approved_for(self, permission: str, subject: str = "") -> bool:
        """Whether the app may do this on its own, as the core last said (`covers`)."""
        return covers(self.approval, permission, subject)

    def _take_approval(self, raw: Any) -> None:
        try:
            approval = Approval.model_validate(raw)
        except ValueError as exc:  # pydantic's ValidationError: the core's words can't be read, the last ones stay
            failed(log, "HiroLeague: reading what the app is approved for", exc)
            return
        if approval != self.approval:
            waits = ", ".join(i["words"] for i in waiting_items(approval))
            log.info("HiroLeague: %s is approved for %s%s", _title(),
                     "everything" if approval.approved is None else f"{len(approval.approved)} things",
                     f"; waiting for the owner: {waits}" if waits else "")
        self.approval = approval

    async def _approval_changed(self, _event: str, data: dict[str, Any]) -> None:
        self._take_approval(data)
        # Fix: a copy the core refused while the app waited (the family list) stayed empty until the 30-minute round;
        # the owner's yes reads every copy again now.
        self.follower.all_again()

    def follow(self, resource: str, refresh: Refresh) -> Callable[[], None]:
        """Keep a copy of `resource` fresh with `refresh()` (follow.py). Returns the function that stops it."""
        return self.follower.follow(resource, refresh)

    def _status(self, status: str, detail: dict[str, Any]) -> None:
        # The SDK awaits this before it reads the connection's frames: never ask the core from here. The bus runs its
        # subscribers on the loop, so they start their requests on their own (family.py).
        if status == STATUS_CONNECTED:
            if detail.get("approval") is not None:  # the welcome's: what it is approved for (Permissions phase 8)
                self._take_approval(detail["approval"])
            bus.publish(CONNECTED)
            self.follower.connected()
            # no name yet and no default address: claim <name>.hiro.local (not awaited here, see above)
            if not self.site_url_set and not ext().site_default:
                self.spawn(self._claim_default(), "claim the default name")

    def on_start(self) -> None:
        # Stopping the worker cancels this task, which closes the connection.
        self.spawn(self._connect(), "connect")
        self.spawn(self.follower.run(), "follow the core's changes")
        # The app's log lines go to the core's log store while the link is up (the SDK's log_sender: it reads the
        # app's own file, so lines logged while the core is away go when it is back)
        if (files := logging_foundation.where()) is not None:
            self.spawn(LogSender(self.client, *files).run(), "send logs")

    async def _connect(self) -> None:
        self._took(await self._read(URL_KEY), await self._read(ADMIN_URL_KEY), await self._read(SITE_URL_KEY))
        await self.client.run()

    def use_settings(self, store: LinkSettings) -> None:
        """Keep the link's settings in `store`, not the app's database (CodeHiro: its own SQLite store), and read them
        from it now, so Settings → HiroLeague shows them before the link starts. Called before `start()`."""
        self.settings = store
        self._took(store.get(URL_KEY), store.get(ADMIN_URL_KEY), store.get(SITE_URL_KEY))

    def _took(self, url: str, admin_url: str, site_url: str) -> None:
        self.admin_url_set, self.site_url_set = admin_url, site_url
        self.client.update_info(info_for(self.site_url()))  # declared with the address set
        self.client.set_url(url)

    async def _read(self, key: str) -> str:
        return await asyncio.to_thread(self.settings.get, key)

    async def _write(self, key: str, value: str) -> None:
        await asyncio.to_thread(self.settings.put, key, value)

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
            "waiting": waiting_items(self.approval),
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
        await self._write(SITE_URL_KEY, url)
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
        await self._write(ADMIN_URL_KEY, url)
        self.admin_url_set = url
        return self.status()

    async def set_url(self, url: str) -> dict[str, Any]:
        url = check_url(url)
        await self._write(URL_KEY, url)
        if url != self.client.url:
            self.approval = None  # another core: what it approves is its own to say, at the welcome
        self.client.set_url(url)
        return self.status()

    def pair(self, code: str) -> dict[str, Any]:
        code = code.strip()
        if not code:
            raise Invalid("Type the pairing code from the core's admin (Extensions, Add an extension).")
        if not self.client.url:
            raise Invalid("Set the core's address first.")
        self.approval = None  # a new pairing: the core says at its welcome what this one is approved for
        self.client.pair(code)
        return self.status()

    def forget(self) -> dict[str, Any]:
        self.approval = None  # unpaired: approved for nothing the core still knows
        self.client.forget()
        return self.status()

    async def apps_for(self, person_id: str) -> list[dict[str, Any]]:
        """The app switcher (UI kit): the apps this person may open, as the core's Apps card lists them, HiroLeague
        first when their role opens its settings and its address is known, this app marked `here`."""
        here = {"extension": ext().name, "title": ext().site_title, "icon": ext().site_icon, "url": self.site_url(),
                "online": True, "here": True}
        if person_id == DEV:
            return [here]  # sign-in off (a dev copy): nobody to ask the core about
        if not self.client.connected:
            raise Unavailable(f"{_title()} isn't connected to HiroLeague right now, so it can't list your other apps.")
        started = calls.start()
        try:
            answer = await self.client.request(METHOD_SITES_LIST, {"person_id": person_id}, timeout=APPS_TIMEOUT)
        except ExtensionRequestError as exc:
            if (refused := refusal(exc)) is not None:
                raise refused from exc
            if exc.code in ("not_connected", "timeout"):
                raise Unavailable(f"HiroLeague didn't answer, so {_title()} can't list your other apps.") from exc
            raise AppsListError(f"HiroLeague couldn't list your apps ({exc.code}): {exc.message}") from exc
        calls.done(log, f"HiroLeague: {METHOD_SITES_LIST}", started, timeout=APPS_TIMEOUT)
        with translate(AppsListError, "HiroLeague's list of apps can't be read"):
            apps = [{"extension": str(a["extension"]), "title": str(a["title"]), "icon": str(a.get("icon") or ""),
                     "url": str(a["url"]), "online": bool(a["online"]), "here": a["extension"] == ext().name}
                    for a in answer["apps"]]
            opens_settings = bool(answer["opens_settings"])
        if not any(a["here"] for a in apps):
            apps.insert(0, here)  # this app's site isn't declared yet (no name): it still shows, as the one you're in
        admin = self.admin_url()
        if opens_settings and admin:
            apps.insert(0, {"extension": CORE_NAME, "title": "HiroLeague", "icon": CORE_NAME, "url": admin,
                            "online": True, "here": False})
        return apps

    async def ask(self, to: str, method: str, params: dict[str, Any] | None = None, *,
                  timeout: float = APPS_ASK_TIMEOUT) -> dict[str, Any]:
        """Ask another app through the core (`extensions.ask`): `ask_app` on this link's client."""
        return await ask_app(self.client, to, method, params, timeout=timeout)

    async def test(self) -> dict[str, Any]:
        """The app's test call: ask the core its name and version."""
        started = time.perf_counter()
        try:
            core = await self.client.request(METHOD_CORE_INFO)
        except ExtensionRequestError as exc:
            raise Invalid(f"The core didn't answer: {exc.message}") from exc
        return {"core": core, "elapsed_ms": round((time.perf_counter() - started) * 1000)}


link = HiroLeagueLink()


async def ask_app(client: Any, to: str, method: str, params: dict[str, Any] | None = None, *,
                  timeout: float = APPS_ASK_TIMEOUT) -> dict[str, Any]:
    """Ask another app through the core (`extensions.ask`, `link.ask`): its answer, or ExtensionRequestError for the
    app's own no, not being connected and the rest, for the app's asks module to say in words. The core's refusals
    (Permissions phase 8: not approved to ask that app) come as the kit's errors, in its words (errors.refusal):
    never asked again."""
    try:
        return await client.ask(to, method, params, timeout=timeout)
    except ExtensionRequestError as exc:
        if (refused := refusal(exc)) is not None:
            raise refused from exc
        raise


async def tell_changed(resource: str, ids: list[str] | None = None) -> bool:
    """Tell the core that something the app keeps changed (`resource.changed`: a hint, never the data), so whatever
    keeps a copy reads it again. `resource` is one the app declares in `Extension.tells`: the core drops any other.
    False when the core isn't connected: events aren't queued, and the core reads again when the app connects."""
    if resource not in {str(t.get("resource") or "") for t in ext().tells}:
        # A programming mistake in the app, caught in its own tests: the core would drop it.
        raise ValueError(f"{resource!r} isn't in Extension.tells: declare it first")
    data: dict[str, Any] = {"resource": resource}
    if ids:
        data["ids"] = list(ids)
    sent = await link.client.send_event(EVENT_TYPE_RESOURCE_CHANGED, data)
    log.debug("Told HiroLeague %s changed%s", resource, "" if sent else " (not connected: not sent)",
              extra={"resource": resource, "ids": len(ids or ())})
    return sent
