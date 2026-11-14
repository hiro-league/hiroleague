"""An app's address as a LAN name the HiroLeague core sets up (hiroleague docs/site-names-design.md): the claim (hiroleague.py `claim_site_name`, PUT /api/hiroleague/site-name) against a fake core
answering `sites.claim`: yes, taken, invalid, and not connected. (The label rules are test_site_name.py.)

Shared-code plan, step 1: HomeHiro's, NetHiro's and TrainHiro's tests each had this file; it is tested once, here."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hiro_channel_sdk import ExtensionClient, ExtensionRequestError
from sqlmodel import Session

from hiro_extension_kit import errors, hiroleague, hiroleague_api, settings
from hiro_extension_kit.db import engine
from hiro_extension_kit.errors import Invalid, Unavailable

from hiro_extension_kit.extension import ext
from hiro_extension_kit.testing import FakeCore

TAKEN = ExtensionRequestError("taken", "testapp.local is taken: another app or the proxy's own file has it.")
INVALID = ExtensionRequestError("invalid", "“x_y.local” can't be an app's name.")


def claimed(params: dict) -> dict:
    """The core's yes on a machine set up for names."""
    return {"name": params["name"], "url": f"http://{params['name']}", "published": True, "proxied": True, "note": ""}


# --- the claim ---------------------------------------------------------------------------------------------------


@pytest.fixture
def core(monkeypatch):
    """A fake core in place of the link's connection: the app's own link and client, with the core's requests and
    `connected` from FakeCore; the reconnect after a claim is only noted."""
    fake = FakeCore()
    link = hiroleague.link
    monkeypatch.setattr(ExtensionClient, "connected", property(lambda _self: fake.connected))
    monkeypatch.setattr(link.client, "request", fake.request)
    link.client.set_url("ws://127.0.0.1:18082")
    fake.reconnects = []  # type: ignore[attr-defined]
    monkeypatch.setattr(link.client, "set_url", lambda url: fake.reconnects.append(url))  # type: ignore[attr-defined]
    monkeypatch.setattr(link, "site_url_set", "")
    yield fake
    link.client.update_info(hiroleague.info_for(hiroleague.site_url_default()))
    ExtensionClient.set_url(link.client, "")  # the class's own: the instance's is still the stand-in here


def saved() -> str | None:
    with Session(engine) as s:
        return settings.get(s, hiroleague.SITE_URL_KEY)


def test_a_free_name_is_claimed_saved_and_declared(core):
    core.answers["sites.claim"] = claimed
    out = asyncio.run(hiroleague.link.claim_site_name("Home", "subdomain"))
    assert core.asked == [("sites.claim", {"name": "home.hiro.local", "port": ext().port})]
    assert core.timeouts == [hiroleague.SITES_TIMEOUT]
    assert (out["url"], out["published"], out["proxied"], out["note"]) == ("http://home.hiro.local", True, True, "")
    assert saved() == "http://home.hiro.local"
    status = out["status"]
    assert (status["site_url"], status["site_label"], status["site_kind"]) == ("http://home.hiro.local", "home", "subdomain")
    assert hiroleague.link.client._info.offers.shows[0]["url"] == "http://home.hiro.local"
    assert core.reconnects == ["ws://127.0.0.1:18082"]  # type: ignore[attr-defined]  # the core reads the new site


def test_a_core_not_set_up_for_names_keeps_the_claim_and_says_why(core):
    note = "This server isn't set up to publish names (hiro extension names); the name is kept for later."
    core.answers["sites.claim"] = lambda p: {**claimed(p), "published": False, "proxied": False, "note": note}
    out = asyncio.run(hiroleague.link.claim_site_name("abc", "local"))
    assert (out["url"], out["published"], out["proxied"], out["note"]) == ("http://abc.local", False, False, note)
    assert saved() == "http://abc.local"


@pytest.mark.parametrize("refusal", [TAKEN, INVALID])
def test_a_taken_or_wrong_name_is_refused_in_the_cores_words_and_nothing_changes(core, refusal):
    core.answers["sites.claim"] = refusal
    with pytest.raises(Invalid) as e:
        asyncio.run(hiroleague.link.claim_site_name("testapp", "local"))
    assert str(e.value) == refusal.message
    assert saved() is None and hiroleague.link.site_url() == hiroleague.site_url_default()
    assert core.reconnects == []  # type: ignore[attr-defined]


def test_not_connected_refuses_before_asking(core):
    core.connected = False
    with pytest.raises(Unavailable) as e:
        asyncio.run(hiroleague.link.claim_site_name("home", "subdomain"))
    assert "isn't connected to HiroLeague, so it can't set up the name" in str(e.value)
    assert core.asked == [] and saved() is None


def test_a_bad_label_is_refused_before_asking(core):
    with pytest.raises(Invalid):
        asyncio.run(hiroleague.link.claim_site_name("a.b", "local"))
    assert core.asked == []


def test_a_core_without_names_or_an_unreadable_answer_is_a_502(core):
    core.answers["sites.claim"] = ExtensionRequestError("method_not_found", "unknown method sites.claim")
    with pytest.raises(hiroleague.SiteNameError) as e:
        asyncio.run(hiroleague.link.claim_site_name("home", "subdomain"))
    assert "method_not_found" in str(e.value)
    core.answers["sites.claim"] = {"name": "home.hiro.local"}  # no published / proxied
    with pytest.raises(hiroleague.SiteNameError):
        asyncio.run(hiroleague.link.claim_site_name("home", "subdomain"))
    assert saved() is None


def test_the_api_answers_the_claim_and_its_refusals(core):
    app = FastAPI()
    app.include_router(hiroleague_api.router)
    errors.install(app)
    client = TestClient(app)
    core.answers["sites.claim"] = claimed
    r = client.put("/api/hiroleague/site-name", json={"label": "home", "kind": "subdomain"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["url"], body["published"], body["proxied"]) == ("http://home.hiro.local", True, True)
    assert body["status"]["site_label"] == "home" and body["status"]["site_kind"] == "subdomain"
    assert client.get("/api/hiroleague").json()["site_url"] == "http://home.hiro.local"
    core.answers["sites.claim"] = TAKEN
    r = client.put("/api/hiroleague/site-name", json={"label": "testapp", "kind": "local"})
    assert r.status_code == 400 and r.json()["detail"] == TAKEN.message
    core.connected = False
    r = client.put("/api/hiroleague/site-name", json={"label": "other", "kind": "local"})
    assert r.status_code == 503 and "can't set up the name" in r.json()["detail"]
    assert client.put("/api/hiroleague/site-name", json={"label": "home", "kind": "web"}).status_code == 422
    assert saved() == "http://home.hiro.local"  # the refusals changed nothing
