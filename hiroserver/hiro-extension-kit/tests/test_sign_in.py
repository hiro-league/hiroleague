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
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from hiro_channel_sdk import ExtensionRequestError
from sqlmodel import Session, select

from hiro_extension_kit import family, hiroleague
from hiro_extension_kit.auth import access, api, sessions
from hiro_extension_kit.auth.identity import Caller, caller_of, device_of
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
    """The fake core, which answers `auth.code` like HiroLeague's: a code it handed out is good once, and comes with the
    person's proof for the app (Permissions phase 8)."""
    monkeypatch.setattr(api, "link", Link(fake_core))
    return fake_core


def code_for(core: FakeCore, person: dict[str, Any], code: str = "one-time") -> str:
    """The core signs `person` in and hands the browser a code for the app."""
    return core.sign_in_code(person, code)


async def _proof(request: Request, _c: Caller = Depends(api.caller)) -> dict[str, str | None]:
    """What a route reads of the person's proof from the core (Permissions phase 8)."""
    return {"proof": hiroleague.core_token(request)}


def _app(lifespan=None) -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.include_router(api.router)
    app.add_api_route("/api/proof", _proof)
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
    assert access.level({"adult": ["status.see", "status.alerts"]}, "status") == "use"
    assert access.level({"adult": ["status.see"]}, "status") == "see"
    assert access.level({"adult": ["settings.change"]}, "settings") == "use"
    assert access.level({"adult": []}, "settings") == "no"
    assert access.level({"kid": ["notes.see:own", "notes.change:own"]}, "notes") == "use"  # their own counts for a page


def test_owner_has_everything_and_no_role_has_nothing():
    owner = access.levels({access.OWNER: []})
    assert owner == {"status": "use", "logs": "see", "settings": "use", "notes": "use"}
    assert set(access.levels({}).values()) == {"no"}
    assert access.rights_of({access.OWNER: []}) == ["status.see", "status.checks", "status.alerts", "status.network",
                                                    "status.diagnose", "logs.see", "settings.change", "notes.see",
                                                    "notes.change"]
    assert access.rights_of({"kid": ["status.see", "bogus.x"]}) == ["status.see"]  # unknown rights drop out


def test_a_persons_rights_add_up_across_their_roles():
    roles = {"kid": ["logs.see", "notes.see:own"], "adult": ["status.see", "notes.see"]}
    assert access.rights_of(roles) == ["status.see", "logs.see", "notes.see"]  # everyone's notes: the wider grant
    assert access.rights_of({"kid": ["notes.see:own", "status.see:own"]}) == ["notes.see:own"]  # status isn't personal
    assert access.levels(roles) == {"status": "see", "logs": "see", "settings": "no", "notes": "see"}


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

    # Permissions phase 8: the session keeps the person's proof the core gave, and routes read it
    proof = client.get("/api/proof").json()["proof"]
    assert proof and core.tokens[proof] == michel["person_id"]
    with Session(engine) as s:
        assert [w.core_token for w in s.exec(select(WebSession))] == [proof]

    out = client.post("/api/auth/logout")  # signs out of HiroLeague too, next
    assert out.status_code == 200 and out.json() == {"then": f"{ADMIN}/api/auth/sign-out?for=test"}
    assert ("auth.end", {"token": proof}) in core.asked  # the proof ends in the core with the session
    assert client.get("/api/me").status_code == 401
    with Session(engine) as s:
        assert s.exec(select(WebSession)).all() == []


def test_signing_out_ends_the_app_session_even_when_the_core_cant_end_the_proof(client, core, caplog):
    come_back(client, code_for(core, join_family(core, "Mark", "kid")))
    proof = client.get("/api/proof").json()["proof"]
    core.answers["auth.end"] = ExtensionRequestError("timeout", "no answer to auth.end in 5s")
    with caplog.at_level("WARNING", logger="testapp.auth"):
        assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/me").status_code == 401
    assert "didn't end the proof of someone who signed out (timeout" in caplog.text
    assert proof and proof not in caplog.text  # the proof itself is never logged


def test_hiroleagues_sign_out_ends_the_proof_too(client, core):
    come_back(client, code_for(core, join_family(core, "Mark", "kid")))
    proof = client.get("/api/proof").json()["proof"]
    client.get("/api/auth/signout", params={"next": f"{ADMIN}/sign-in"})
    assert ("auth.end", {"token": proof}) in core.asked


def test_with_sign_in_off_there_is_no_proof(client, monkeypatch):
    testing.auth(monkeypatch, False)
    assert client.get("/api/proof").json() == {"proof": None}


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
    assert (me["state"], me["role_names"]) == ("ok", ["Adult"])


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
        assert adult.request(method, path, json={"role_ids": ["owner"]}).status_code == 403, (method, path)


def test_the_owner_gives_roles_and_they_apply_at_once(client, core):
    """The roles are the family list's, set on the user's core person; No access is the app's own."""
    michel, mark = join_family(core, "Michel Habib", "owner"), join_family(core, "Mark", "adult")
    owner, them = signed_in(core, michel), signed_in(core, mark)
    mid = mark["person_id"]
    assert them.get("/api/me").json()["role_names"] == ["Adult"]
    assert owner.put(f"/api/users/{mid}", json={"role_ids": ["kid"]}).status_code == 200
    assert ("people.update", {"person_id": mid, "role_ids": ["kid"]}) in core.asked
    proof = owner.get("/api/proof").json()["proof"]
    assert ("people.update", proof) in core.signed_in  # asked for the owner signed in, with their proof
    assert them.get("/api/me").json()["role_names"] == ["Kid"]
    users = owner.put(f"/api/users/{mid}", json={"role_ids": ["kid", "adult"]}).json()
    assert next(u for u in users if u["id"] == mid)["role_ids"] == ["adult", "kid"]  # in the roles' order
    me = them.get("/api/me").json()
    assert (me["role_ids"], me["role_names"]) == (["adult", "kid"], ["Adult", "Kid"])
    kid = next(r for r in owner.get("/api/roles").json()["roles"] if r["id"] == "kid")
    assert kid["users"] == ["Mark"]  # a user shows under every role they hold

    asked = len(core.asked)
    owner.put(f"/api/users/{mid}", json={"denied": True})
    assert them.get("/api/me").json()["state"] == "denied"
    assert len(core.asked) == asked  # nothing was asked of HiroLeague
    owner.put(f"/api/users/{mid}", json={"denied": False})  # back in, with the roles they hold
    assert them.get("/api/me").json()["role_names"] == ["Adult", "Kid"]
    assert owner.put(f"/api/users/{mid}", json={"role_ids": []}).status_code == 400  # neither a role nor No access


def test_no_app_gives_or_takes_the_owner_role(client, core):
    """Permissions phase 8: the Owner role is given in HiroLeague's admin only (the core refuses it too). The page
    sends every role a user holds, so an owner keeping it is no change."""
    michel, mark = join_family(core, "Michel Habib", "owner"), join_family(core, "Mark", "adult")
    owner = signed_in(core, michel)
    signed_in(core, mark)
    asked = len(core.asked)
    for who, roles in [(michel, ["adult"]), (mark, ["owner"]), (mark, ["owner", "adult"])]:
        r = owner.put(f"/api/users/{who['person_id']}", json={"role_ids": roles})
        assert r.status_code == 400 and r.json()["detail"] == "The Owner role is given in HiroLeague's admin.", roles
    assert len(core.asked) == asked  # nothing was asked of HiroLeague
    assert owner.put(f"/api/users/{michel['person_id']}", json={"role_ids": ["owner", "kid"]}).status_code == 200
    r = owner.put(f"/api/users/{michel['person_id']}", json={"denied": True})  # the only owner keeps their access
    assert r.status_code == 400 and "only owner" in r.json()["detail"]


def test_the_cores_no_for_the_person_is_passed_on_in_its_words(client, core):
    """The core answers a change by the person signed in: a proof it no longer knows asks them to sign in again (401),
    an app the owner didn't approve to act for people is refused (403), in the core's words."""
    michel, mark = join_family(core, "Michel Habib", "owner"), join_family(core, "Mark", "adult")
    owner = signed_in(core, michel)
    signed_in(core, mark)
    core.approved = ["people.see"]  # approved for less than to act for the people signed in to it
    r = owner.put(f"/api/users/{mark['person_id']}", json={"role_ids": ["kid"]})
    assert r.status_code == 403 and "isn't approved to act for the people signed in to it" in r.json()["detail"]
    core.approved = None
    core.tokens.clear()  # the core ended the proof (a new password, say)
    r = owner.put(f"/api/users/{mark['person_id']}", json={"role_ids": ["kid"]})
    assert (r.status_code, r.json()["detail"]) == (401, "Sign in again to do this.")


def test_someone_gone_from_the_family_list_cant_be_given_a_role(client, core):
    michel, mark = join_family(core, "Michel Habib", "owner"), join_family(core, "Mark", "adult")
    owner, them = signed_in(core, michel), signed_in(core, mark)
    core.people.remove(mark)
    asyncio.run(family.sync())
    r = owner.put(f"/api/users/{mark['person_id']}", json={"role_ids": ["kid"]})
    assert r.status_code == 400 and "isn't in HiroLeague's family list any more" in r.json()["detail"]
    assert them.get("/api/me").json()["state"] == "waiting"


def test_roles_are_shown_as_hiroleague_grants_them(client, core):
    michel = join_family(core, "Michel Habib", "owner")
    next(r for r in core.roles if r["role_id"] == "kid").update(rights=["status.see", "logs.see"], says="The kids")
    signed_in(core, join_family(core, "Mark", "kid"))
    roles = signed_in(core, michel).get("/api/roles").json()
    assert [r["name"] for r in roles["roles"]] == ["Owner", "Adult", "Kid"]
    assert [f["id"] for f in roles["features"]] == ["status", "logs", "settings", "notes"]
    kid = next(r for r in roles["roles"] if r["id"] == "kid")
    assert (kid["users"], kid["says"], kid["rights"]) == (["Mark"], "The kids", ["status.see", "logs.see"])
    assert kid["access"] == {"status": "see", "logs": "see", "settings": "no", "notes": "no"}


def test_with_sign_in_off_everyone_is_the_owner(client, monkeypatch):
    testing.auth(monkeypatch, False)
    me = client.get("/api/me").json()
    assert (me["way"], me["owner"]) == ("dev", True)
    assert client.get("/api/roles").status_code == 200
