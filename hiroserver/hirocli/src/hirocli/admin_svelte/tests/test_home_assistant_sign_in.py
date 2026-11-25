"""'Sign in with Home Assistant', run by the core (trust fixes, Nov 25): an option the owner adds on People → Sign-in.

Against a fake Home Assistant on 127.0.0.1 (fake_home_assistant.py). The access token is kept by the core and never
answered.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from hirocli.admin_svelte.route_rules import require_rule
from hirocli.admin_svelte.routes import auth as auth_routes
from hirocli.admin_svelte.routes.auth import RequireSignIn, auth_router
from hirocli.admin_svelte.routes.sign_in_ways import sign_in_ways_router
from hirocli.admin_svelte.tests.fake_home_assistant import FakeHa, RunningFakeHa
from hirocli.domain import home_assistant_sign_in as ha_sign_in
from hirocli.domain.admin_sign_in import give_sign_in
from hirocli.domain.home_assistant_sign_in import HaLogin, HaSignInError
from hirocli.domain.people import add_person
from hirocli.runtime import sign_in_for_extensions as sign_in
from hirocli.services import home_assistant
from hirocli.services.home_assistant import HomeAssistantError

HOME_INFO = {"name": "home", "offers": {"shows": [{"kind": "site", "title": "Home", "url": "http://homehiro.local"}]}}


@pytest.fixture
def ha() -> Iterator[FakeHa]:
    running = RunningFakeHa(FakeHa())
    yield running.start()
    running.stop()


@pytest.fixture
def family(tmp_path: Path) -> dict[str, Any]:
    auth_routes._failures.clear()
    sign_in.CODES.__init__()
    michel = add_person(tmp_path, name="Michel", role_id="owner")
    give_sign_in(tmp_path, michel.person_id, sign_in="michel", password="correct horse")
    mark = add_person(tmp_path, name="Mark", role_id="kid")
    give_sign_in(tmp_path, mark.person_id, sign_in="mark", password="kid password")
    app = FastAPI()
    app.state.ctx = SimpleNamespace(workspace_path=tmp_path, config=SimpleNamespace(admin_port=18083),
                                    extension_manager=SimpleNamespace(snapshot=lambda: {"e-home": {"info": HOME_INFO}}))
    app.add_middleware(RequireSignIn, ctx=app.state.ctx)
    api = APIRouter(prefix="/api", dependencies=[Depends(require_rule)])  # as admin_svelte/api.py
    api.include_router(auth_router)
    api.include_router(sign_in_ways_router)
    app.include_router(api)
    return {"path": tmp_path, "michel": michel, "mark": mark, "client": TestClient(app, follow_redirects=False)}


def _sign_in(client: TestClient, name: str, password: str) -> None:
    assert client.post("/api/auth/sign-in", json={"sign_in": name, "password": password}).status_code == 200


def _connected(family: dict[str, Any], ha: FakeHa, on: bool = True, link: str = "") -> None:
    """Connected, Mark's login linked to Mark (the owner's link); Michel's only suggested."""
    version, found = asyncio.run(home_assistant.check(ha.url, ha.admin_token))
    ha_sign_in.connected(family["path"], ha.url, link, ha.admin_token, version, found)
    ha_sign_in.link(family["path"], "u-mark", family["mark"].person_id)
    ha_sign_in.set_enabled(family["path"], on)


# --- who is who ----------------------------------------------------------------------------------------------------


def test_a_login_is_only_suggested_by_name_and_linked_only_as_the_owner_linked_it() -> None:
    found = [HaLogin("u1", "Michel", "michel"), HaLogin("u2", "mark ", "mark"), HaLogin("u3", "Mona", "mona"),
             HaLogin("u4", "Joe", "joe")]
    family = {"p-michel": "Michel", "p-mark": "Mark", "p-joe": "Joe", "p-joe2": "joe"}
    out = ha_sign_in.suggested(found, {"u3": "p-michel"}, family)
    assert [lg.suggested_id for lg in out] == ["p-michel", "p-mark", "", ""]  # Joe twice: no suggestion
    assert [lg.person_id for lg in out] == ["", "", "p-michel", ""]  # only the owner's link


# --- the connection test -------------------------------------------------------------------------------------------


def test_the_connection_test_reads_the_version_and_who_can_log_in(ha: FakeHa) -> None:
    version, found = asyncio.run(home_assistant.check(ha.url, ha.admin_token))
    assert version == "2026.11.2"
    assert [(lg.ha_user_id, lg.name, lg.login) for lg in found] == [
        ("u-michel", "Michel", "michel"), ("u-mark", "Mark", "mark"), ("u-guest", "Guest", "guest")]  # no cat
    # A token of a user who isn't an administrator: the people still, their login names left blank
    _version, plain = asyncio.run(home_assistant.check(ha.url, ha.plain_token))
    assert [lg.login for lg in plain] == ["", "", ""]


@pytest.mark.parametrize(("address", "token", "said"), [
    ("ha.local", "x", "must start with http"),
    ("http://127.0.0.1:1", "x", "couldn't be reached"),
])
def test_a_connection_that_fails_says_why_in_words(address: str, token: str, said: str) -> None:
    with pytest.raises(HomeAssistantError, match=said):
        asyncio.run(home_assistant.check(address, token))


def test_a_wrong_token_is_refused_in_words(ha: FakeHa) -> None:
    with pytest.raises(HomeAssistantError, match="didn't accept the access token"):
        asyncio.run(home_assistant.check(ha.url, "wrong"))


# --- the owner's page ----------------------------------------------------------------------------------------------


def test_the_owner_connects_links_and_turns_it_on_and_the_token_never_leaves(family: dict[str, Any], ha: FakeHa) -> None:
    client = family["client"]
    _sign_in(client, "michel", "correct horse")
    assert client.get("/api/sign-in/home-assistant").json()["connected"] is False
    refused = client.put("/api/sign-in/home-assistant/enabled", json={"on": True})
    assert refused.status_code == 400 and "Connect Home Assistant first" in refused.json()["detail"]

    r = client.put("/api/sign-in/home-assistant/connection", json={"address": ha.url + "/", "token": ha.admin_token})
    state = r.json()
    assert r.status_code == 200 and state["connected"] and state["version"] == "2026.11.2" and state["token_set"]
    assert state["address"] == ha.url
    assert {lg["name"]: lg["suggested_id"] for lg in state["logins"]} == {
        "Guest": "", "Mark": family["mark"].person_id, "Michel": family["michel"].person_id}
    assert {lg["person_id"] for lg in state["logins"]} == {""}  # suggested, linked to nobody yet
    assert ha.admin_token not in r.text  # the token is kept in the keyring, never answered
    assert ha_sign_in.token(family["path"]) == ha.admin_token

    # Test again with the token kept; a new address needs it typed again; a bad one is refused in words
    assert client.put("/api/sign-in/home-assistant/connection", json={"address": ha.url}).status_code == 200
    moved = client.put("/api/sign-in/home-assistant/connection", json={"address": "http://elsewhere.local"})
    assert moved.status_code == 400 and "again for a new address" in moved.json()["detail"]
    bad = client.put("/api/sign-in/home-assistant/connection", json={"address": ha.url, "token": "wrong"})
    assert bad.status_code == 502 and "didn't accept the access token" in bad.json()["detail"]

    assert client.put("/api/sign-in/home-assistant/logins/u-guest", json={"person_id": "nobody"}).status_code == 400
    linked = client.put("/api/sign-in/home-assistant/logins/u-guest", json={"person_id": family["mark"].person_id})
    assert {lg["name"]: lg["person_id"] for lg in linked.json()["logins"]}["Guest"] == family["mark"].person_id

    assert client.put("/api/sign-in/home-assistant/enabled", json={"on": True}).json()["enabled"] is True
    assert client.get("/api/auth/me").json()["sign_in_offers"] == [{"id": "home_assistant", "label": "Home Assistant"}]

    off = client.delete("/api/sign-in/home-assistant/connection").json()
    assert (off["connected"], off["enabled"], off["token_set"]) == (False, False, False)
    assert len(off["logins"]) == 3  # who is who stays for a later connection
    assert client.get("/api/auth/me").json()["sign_in_offers"] == []


def test_only_the_owner_reaches_the_sign_in_ways(family: dict[str, Any]) -> None:
    client = family["client"]
    _sign_in(client, "mark", "kid password")
    assert client.get("/api/sign-in/home-assistant").status_code == 403


def test_switching_it_on_needs_a_connection(family: dict[str, Any]) -> None:
    with pytest.raises(HaSignInError):
        ha_sign_in.set_enabled(family["path"], True)


# --- signing in ----------------------------------------------------------------------------------------------------


def test_signing_in_with_home_assistant_is_run_by_the_core(family: dict[str, Any], ha: FakeHa) -> None:
    _connected(family, ha, link="http://homeassistant.local")
    client = family["client"]
    start = client.get("/api/auth/with/home_assistant", params={"for": "home", "next": "/people"})
    where = urlsplit(start.headers["location"])
    # The browser logs in at the address people use; the core trades the code at its own
    assert start.status_code == 303 and f"{where.scheme}://{where.netloc}{where.path}" == "http://homeassistant.local/auth/authorize"
    asked = {k: v[0] for k, v in parse_qs(where.query).items()}
    assert asked["client_id"] == "http://testserver/"
    assert asked["redirect_uri"] == "http://testserver/api/auth/with/callback"

    ha.codes["code-1"] = "u-mark"
    done = client.get("/api/auth/with/callback", params={"code": "code-1", "state": asked["state"]})
    assert done.status_code == 303 and done.headers["location"] == "/api/auth/for/home?next=%2Fpeople"
    assert client.get("/api/auth/me").json()["person"]["name"] == "Mark"
    assert ha.revoked == ["refresh-u-mark"]  # no login left in their Home Assistant profile

    again = client.get("/api/auth/with/callback", params={"code": "code-1", "state": asked["state"]})
    assert "signin_error" in again.headers["location"]  # a state works once


@pytest.mark.parametrize(("user", "name"), [("u-guest", "Guest"), ("u-michel", "Michel")])
def test_a_login_the_owner_didnt_link_signs_nobody_in_even_when_suggested(
        family: dict[str, Any], ha: FakeHa, user: str, name: str) -> None:
    # Michel's login is suggested as the Owner by name: a suggestion signs nobody in
    _connected(family, ha)
    client = family["client"]
    state = parse_qs(urlsplit(client.get("/api/auth/with/home_assistant").headers["location"]).query)["state"][0]
    ha.codes["code-2"] = user
    r = client.get("/api/auth/with/callback", params={"code": "code-2", "state": state})
    assert parse_qs(urlsplit(r.headers["location"]).query)["signin_error"] == [
        f"{name}'s Home Assistant login isn't linked to anyone in the family list. The owner links it on People → Sign-in."]
    assert client.get("/api/auth/me").json()["signed_in"] is False


def test_a_code_home_assistant_refuses_signs_nobody_in(family: dict[str, Any], ha: FakeHa) -> None:
    _connected(family, ha)
    client = family["client"]
    state = parse_qs(urlsplit(client.get("/api/auth/with/home_assistant").headers["location"]).query)["state"][0]
    r = client.get("/api/auth/with/callback", params={"code": "made-up", "state": state})
    assert "didn't accept the sign-in" in parse_qs(urlsplit(r.headers["location"]).query)["signin_error"][0]
    assert client.get("/api/auth/me").json()["signed_in"] is False


def test_switched_off_there_is_no_button_and_no_way_in(family: dict[str, Any], ha: FakeHa) -> None:
    _connected(family, ha, on=False)
    client = family["client"]
    assert client.get("/api/auth/me").json()["sign_in_offers"] == []
    r = client.get("/api/auth/with/home_assistant")
    assert "isn't available" in parse_qs(urlsplit(r.headers["location"]).query)["signin_error"][0]
