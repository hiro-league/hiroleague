"""Settings → HiroLeague: the core's address, the app's own address (Phase 8; a name the core sets up since the site
names change), pairing, and the test call (hiroleague.py keeps the connection)."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from .hiroleague import link

router = APIRouter()


class CoreInfo(BaseModel):
    name: str
    version: str
    workspace: str = ""
    admin_port: int | None = None  # Phase 7b: the core's admin web port


class HiroLeagueStatus(BaseModel):
    url: str  # the core's extension address, e.g. ws://127.0.0.1:18082; "" when not set
    status: str  # no_address | not_paired | connecting | connected | disconnected | stopped
    error: str | None = None  # why it isn't connected, in words
    core: CoreInfo | None = None  # while connected
    admin_url_set: str = ""  # the admin's address as set here; "" = derived
    admin_url: str = ""  # where the app's links open the core's admin ("" while unknown)
    site_url_set: str = ""  # Phase 8: the app's address as set here; "" = the default
    site_url: str = ""  # Phase 8: the app's address declared to the core (its Apps card, where sign-in comes back)
    site_label: str | None = None  # site_url's name for the form: home (home.hiro.local), nethiro (nethiro.local)
    site_kind: Literal["subdomain", "local"] | None = None  # None: site_url isn't one of the two names


class HiroLeagueTest(BaseModel):
    core: CoreInfo
    elapsed_ms: int


class UrlIn(BaseModel):
    url: str  # "" clears it


class AdminUrlIn(BaseModel):
    url: str  # "" = derive it from the core's host and admin port


class SiteNameIn(BaseModel):
    """The app's name: a subdomain label (home → home.hiro.local) or a one-word .local name (abc → abc.local)."""

    label: str
    kind: Literal["subdomain", "local"]


class SiteNameOut(BaseModel):
    """The core's answer to the claim (sites.claim) and Settings → HiroLeague as it now is."""

    name: str  # e.g. home.hiro.local
    url: str  # http://<name>, now the app's address
    published: bool  # the name is on the LAN (mDNS)
    proxied: bool  # the core's web proxy sends the name to the app
    note: str = ""  # why not published or proxied, in the core's words
    status: HiroLeagueStatus


class PairIn(BaseModel):
    code: str


@router.get("/api/hiroleague")
async def hiroleague_status() -> HiroLeagueStatus:
    return HiroLeagueStatus.model_validate(link.status())


@router.put("/api/hiroleague")
async def hiroleague_set_url(body: UrlIn) -> HiroLeagueStatus:
    return HiroLeagueStatus.model_validate(await link.set_url(body.url))


@router.put("/api/hiroleague/admin-url")
async def hiroleague_set_admin_url(body: AdminUrlIn) -> HiroLeagueStatus:
    """Phase 7b: the address people open the core's admin at (the Edit links), e.g. http://hiro.local."""
    return HiroLeagueStatus.model_validate(await link.set_admin_url(body.url))


@router.put("/api/hiroleague/site-name")
async def hiroleague_set_site_name(body: SiteNameIn) -> SiteNameOut:
    """The app's own address (Phase 8), declared to the core: its Apps card opens it, and the core sends people back
    only there after signing them in. A name the core sets up on the LAN (sites.claim), no longer a typed URL
    (/api/hiroleague/site-url): a taken or wrong name is refused (400) and nothing changes."""
    return SiteNameOut.model_validate(await link.claim_site_name(body.label, body.kind))


@router.post("/api/hiroleague/pair")
async def hiroleague_pair(body: PairIn) -> HiroLeagueStatus:
    return HiroLeagueStatus.model_validate(link.pair(body.code))


@router.post("/api/hiroleague/forget")
async def hiroleague_forget() -> HiroLeagueStatus:
    return HiroLeagueStatus.model_validate(link.forget())


@router.post("/api/hiroleague/test")
async def hiroleague_test() -> HiroLeagueTest:
    return HiroLeagueTest.model_validate(await link.test())
