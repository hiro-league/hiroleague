"""One sign-in: a signed-out browser goes to HiroLeague's sign-in page and comes back with a one-time code, which the app
redeems with the core (auth/api.py, `auth.code`) for its own session (auth/sessions.py). Then who is asking (/api/me),
and the owner's Settings → Users and Roles, against a fake core.

Shared-code plan, step 1: HomeHiro's, NetHiro's and TrainHiro's tests each had this file; it is tested once, here. An
app's own way in (HomeHiro: HA's add-on) and its features' ids stay in the app's tests."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hiro_channel_sdk import ExtensionRequestError
from sqlmodel import Session, select

from hiro_extension_kit import family
from hiro_extension_kit.auth import access, api, sessions
from hiro_extension_kit.auth.identity import caller_of, device_of
from hiro_extension_kit import errors
from hiro_extension_kit.db import engine
from hiro_extension_kit.auth.models import CorePerson, WebSession

from hiro_extension_kit import testing
from hiro_extension_kit.testing import FakeCore, join_family

ADMIN = "http://hiro.local"
IPHONE_APP = "Home Assistant/2026.9.2 (io.robbie.HomeAssistant; build:2026.1501; iOS 26.0.1) Mobile/HomeAssistant"
ANDROID_APP = "Mozilla/5.0 (Linux; Android 16; SM-S908E Build/BP2A; wv) AppleWebKit/537.36 Chrome/153.0 Mobile Safari/537.36"
WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153.0 Safari/537.36"


class Link:
    """hiroleague.link as auth/api.py uses it: the client (the fake core) and the admin's address."""

    def __init__(self, client: FakeCore, admin: str = ADMIN) -> None:
        self.client = client
        self.admin = admin

    def admin_url(self) -> str:
        return self.admin


@pytest.fixture
def core(fake_core, monkeypatch):
    """The fake core, which also answers `auth.code` like HiroLeague's: a code it handed out is good once."""
    codes: dict[str, dict[str, Any]] = {}

    def redeem(params: dict[str, Any]) -> dict[str, Any]:
        who = codes.pop(params.get("code", ""), None)
        if who is None:
            return ExtensionRequestError("invalid_code", "That code is unknown, used or expired.")  # type: ignore[return-value]
        return who

    fake_core.codes = codes
    fake_core.answers["auth.code"] = redeem
    monkeypatch.setattr(api, "link", Link(fake_core))
    return fake_core


def code_for(core: FakeCore, person: dict[str, Any], code: str = "one-time") -> str:
    """The core signs `person` in and hands the browser a code for the app."""
    role = next(r for r in core.roles if r["role_id"] == person["role_id"])
    core.codes[code] = {"person_id": person["person_id"], "name": person["name"], "role_id": role["role_id"],  # type: ignore[attr-defined]
                        "role_name": role["name"]}
    return code


def _app(lifespan=None) -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.include_router(api.router)
    errors.install(app)
    return app


@pytest.fixture
def client(core, monkeypatch):
    testing.auth(monkeypatch, True)
    with TestClient(_app(), follow_redirects=False) as c:
        yield c


def come_back(client, code: str, next_path: str = "/status"):
    return client.get("/api/auth/hiro", params={"code": code, "next": next_path})


def signed_in(core: FakeCore, person: dict[str, Any], ua: str = WINDOWS) -> TestClient:
    """Another browser, signed in as `person` (its own cookie jar)."""
    c = TestClient(_app(), follow_redirects=False, headers={"User-Agent": ua})
    assert come_back(c, code_for(core, person, f"code-{person['person_id']}-{ua[:8]}")).status_code == 303
    return c


# ---- pure rules


def test_the_pages_level_comes_from_the_rights():
    """"use" with any right beyond See, "see" with See only; a feature without See is "use" with its right."""
    assert access.level("adult", ["status.see", "status.alerts"], "status") == "use"
    assert access.level("adult", ["status.see"], "status") == "see"
    assert access.level("adult", ["settings.change"], "settings") == "use"
    assert access.level("adult", [], "settings") == "no"


def test_owner_has_everything_and_no_role_has_nothing():
    owner = access.levels(access.OWNER, [])
    assert owner == {"status": "use", "logs": "see", "settings": "use"}
    assert set(access.levels(None, ["status.see", "status.checks"]).values()) == {"no"}
    assert access.rights_of(access.OWNER, []) == ["status.see", "status.checks", "status.alerts", "status.network",
                                                  "status.diagnose", "logs.see", "settings.change"]
    assert access.rights_of("kid", ["status.see", "bogus.x"]) == ["status.see"]  # unknown rights drop out


def test_devices_are_named_from_the_user_agent():
    assert device_of(IPHONE_APP) == "iPhone"
    assert device_of(ANDROID_APP) == "Android phone"
    assert device_of(WINDOWS) == "Windows PC"
    assert device_of("") == "a browser"


def test_no_header_names_anyone():
    """Phase 9b: HA's add-on headers stayed with HomeHiro; only sign-in off names someone without a session."""
    assert caller_of({"x-remote-user-id": "u-michel", "x-homehiro-proxy": "s3cret"}, True) is None
    assert caller_of({}, False).way == "dev"  # type: ignore[union-attr]


# ---- signed out: off to HiroLeague, and back with a code


def test_a_signed_out_browser_goes_to_hiroleagues_sign_in_page(client):
    assert client.get("/api/me").status_code == 401
    r = client.get("/api/auth/start", params={"next": "/status?tab=2"})
    assert r.status_code == 303
    to = urlparse(r.headers["location"])
    assert f"{to.scheme}://{to.netloc}{to.path}" == f"{ADMIN}/sign-in"
    assert parse_qs(to.query) == {"for": ["test"], "next": ["/status?tab=2"]}
    for bad in ("//evil.example/x", "https://evil.example", "/\\evil.example"):
        r = client.get("/api/auth/start", params={"next": bad})
        assert parse_qs(urlparse(r.headers["location"]).query)["next"] == ["/"], bad


def test_without_hiroleagues_address_it_says_so(client, core, monkeypatch):
    monkeypatch.setattr(api, "link", Link(core, admin=""))
    r = client.get("/api/auth/start")
    assert r.status_code == 303 and r.headers["location"].startswith("/?signin_error=")
    assert "address" in r.headers["location"]


def test_coming_back_with_a_code_signs_in_as_the_core_person(client, core):
    michel = join_family(core, "Michel Habib", "owner")
    back = come_back(client, code_for(core, michel))
    assert back.status_code == 303 and back.headers["location"] == "/status"
    assert ("auth.code", {"code": "one-time"}) in core.asked
    cookie = back.headers["set-cookie"].lower()
    assert sessions.COOKIE in cookie and "samesite=lax" in cookie and "httponly" in cookie
    assert f"max-age={90 * 86400}" in cookie  # 90 days

    me = client.get("/api/me").json()
    assert (me["id"], me["name"], me["way"], me["owner"]) == (michel["person_id"], "Michel Habib", "web", True)

    out = client.post("/api/auth/logout")  # signs out of HiroLeague too, next
    assert out.status_code == 200 and out.json() == {"then": f"{ADMIN}/api/auth/sign-out?for=test"}
    assert client.get("/api/me").status_code == 401
    with Session(engine) as s:
        assert s.exec(select(WebSession)).all() == []


def test_a_code_is_good_once(client, core):
    mark = join_family(core, "Mark", "kid")
    code = code_for(core, mark)
    assert come_back(client, code).headers["location"] == "/status"
    client.cookies.clear()
    again = come_back(client, code)
    assert again.status_code == 303 and again.headers["location"].startswith("/?signin_error=")
    assert "expired" in again.headers["location"] and client.get("/api/me").status_code == 401


def test_no_code_or_the_core_away_says_why(client, core):
    r = come_back(client, "")
    assert r.headers["location"].startswith("/?signin_error=") and "code" in r.headers["location"]
    core.connected = False
    r = come_back(client, "anything")
    assert r.headers["location"].startswith("/?signin_error=") and "connected" in r.headers["location"]


def test_it_only_goes_back_to_a_page_of_the_app(client, core):
    mark = join_family(core, "Mark", "kid")
    for bad in ("//evil.example/x", "https://evil.example", "/\\evil.example"):
        back = come_back(client, code_for(core, mark), next_path=bad)
        assert back.headers["location"] == "/", bad
        client.post("/api/auth/logout")
        client.cookies.clear()


def test_someone_new_to_the_family_list_is_read_in_first(client, core):
    """A person the app's copy doesn't have yet: the copy is read again, so their role is known at once."""
    new = core.person("Sara", "adult")
    with Session(engine) as s:
        assert s.get(CorePerson, new["person_id"]) is None
    come_back(client, code_for(core, new))
    me = client.get("/api/me").json()
    assert (me["state"], me["role_name"]) == ("ok", "Adult")


def test_an_expired_session_signs_in_nobody(client, core):
    come_back(client, code_for(core, join_family(core, "Mark", "kid")))
    with Session(engine) as s:
        for w in s.exec(select(WebSession)):
            w.expires_at = datetime.now(UTC) - timedelta(minutes=1)
            s.add(w)
        s.commit()
    assert client.get("/api/me").status_code == 401
    with Session(engine) as s:
        assert sessions.purge(s) == 1


def test_a_forged_cookie_signs_in_nobody(client):
    client.cookies.set(sessions.COOKIE, "made-up")
    assert client.get("/api/me").status_code == 401


def test_hiroleagues_sign_out_passes_through_and_goes_back_only_to_hiroleague(client, core):
    """HiroLeague's Sign out sends the browser through /api/auth/signout: the app's session ends, then back to
    HiroLeague's own address, never anywhere else."""
    come_back(client, code_for(core, join_family(core, "Mark", "kid")))
    r = client.get("/api/auth/signout", params={"next": f"{ADMIN}/sign-in"})
    assert r.status_code == 303 and r.headers["location"] == f"{ADMIN}/sign-in"
    assert client.get("/api/me").status_code == 401
    for bad in ("https://evil.example/sign-in", "//evil.example", "/status"):
        r = client.get("/api/auth/signout", params={"next": bad})
        assert r.headers["location"] == "/", bad


# ---- Settings → Users and Roles


def test_only_an_owner_manages_users_and_roles(client, core):
    michel, mark = join_family(core, "Michel", "owner"), join_family(core, "Mark", "adult")
    owner, adult = signed_in(core, michel), signed_in(core, mark, ANDROID_APP)
    users = {u["id"]: u for u in owner.get("/api/users").json()}
    assert set(users) == {michel["person_id"], mark["person_id"]}
    assert users[mark["person_id"]]["last_device"] == "Android phone"
    for method, path in [("get", "/api/users"), ("get", "/api/roles"), ("put", f"/api/users/{mark['person_id']}")]:
        assert adult.request(method, path, json={"role_id": "owner"}).status_code == 403, (method, path)


def test_the_owner_gives_a_role_and_it_applies_at_once(client, core):
    """The role is the family list's, set on the user's core person; No access is the app's own."""
    michel, mark = join_family(core, "Michel Habib", "owner"), join_family(core, "Mark", "adult")
    owner, them = signed_in(core, michel), signed_in(core, mark)
    mid = mark["person_id"]
    assert them.get("/api/me").json()["role_name"] == "Adult"
    assert owner.put(f"/api/users/{mid}", json={"role_id": "kid"}).status_code == 200
    assert ("people.update", {"person_id": mid, "role_id": "kid"}) in core.asked
    assert them.get("/api/me").json()["role_name"] == "Kid"

    asked = len(core.asked)
    owner.put(f"/api/users/{mid}", json={"denied": True})
    assert them.get("/api/me").json()["state"] == "denied"
    assert len(core.asked) == asked  # nothing was asked of HiroLeague
    assert owner.put(f"/api/users/{mid}", json={}).status_code == 400  # neither a role nor No access


def test_the_only_owner_stays_one(client, core):
    """HiroLeague refuses taking the only Owner's role away, and the app passes its words on."""
    michel, mark = join_family(core, "Michel Habib", "owner"), join_family(core, "Mark", "adult")
    owner = signed_in(core, michel)
    signed_in(core, mark)
    r = owner.put(f"/api/users/{michel['person_id']}", json={"role_id": "adult"})
    assert r.status_code == 400 and r.json()["detail"] == "Michel Habib is the only Owner; make someone else Owner first."
    r = owner.put(f"/api/users/{michel['person_id']}", json={"denied": True})  # nor No access
    assert r.status_code == 400 and "only owner" in r.json()["detail"]
    # with a second owner, the first may step down (HomeHiro's test_auth checked this too)
    assert owner.put(f"/api/users/{mark['person_id']}", json={"role_id": "owner"}).status_code == 200
    assert owner.put(f"/api/users/{michel['person_id']}", json={"role_id": "adult"}).status_code == 200


def test_someone_gone_from_the_family_list_cant_be_given_a_role(client, core):
    michel, mark = join_family(core, "Michel Habib", "owner"), join_family(core, "Mark", "adult")
    owner, them = signed_in(core, michel), signed_in(core, mark)
    core.people.remove(mark)
    asyncio.run(family.sync())
    r = owner.put(f"/api/users/{mark['person_id']}", json={"role_id": "kid"})
    assert r.status_code == 400 and "isn't in HiroLeague's family list any more" in r.json()["detail"]
    assert them.get("/api/me").json()["state"] == "waiting"


def test_roles_are_shown_as_hiroleague_grants_them(client, core):
    michel = join_family(core, "Michel Habib", "owner")
    next(r for r in core.roles if r["role_id"] == "kid").update(rights=["status.see", "logs.see"], says="The kids")
    signed_in(core, join_family(core, "Mark", "kid"))
    roles = signed_in(core, michel).get("/api/roles").json()
    assert [r["name"] for r in roles["roles"]] == ["Owner", "Adult", "Kid"]
    assert [f["id"] for f in roles["features"]] == ["status", "logs", "settings"]
    kid = next(r for r in roles["roles"] if r["id"] == "kid")
    assert (kid["users"], kid["says"], kid["rights"]) == (["Mark"], "The kids", ["status.see", "logs.see"])
    assert kid["access"] == {"status": "see", "logs": "see", "settings": "no"}


def test_with_sign_in_off_everyone_is_the_owner(client, monkeypatch):
    testing.auth(monkeypatch, False)
    me = client.get("/api/me").json()
    assert (me["way"], me["owner"]) == ("dev", True)
    assert client.get("/api/roles").status_code == 200
