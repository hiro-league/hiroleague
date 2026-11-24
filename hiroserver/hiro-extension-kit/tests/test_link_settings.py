"""The link's settings kept in a store the app hands it (hiroleague.py `use_settings`, `LinkSettings`), its site shown to
some roles only (`Extension.site_roles`), and the one sign-in's helpers that only talk to the core (auth/one_sign_in.py).

Unified communication, phase 6: CodeHiro keeps its own SQLite store, not the kit's database, and connects, describes
itself and signs people in through the kit's link all the same."""

import asyncio
import dataclasses

import pytest
from hiro_channel_sdk import ExtensionClient, ExtensionRequestError

from hiro_extension_kit import extension, hiroleague
from hiro_extension_kit.auth import one_sign_in
from hiro_extension_kit.errors import Invalid, OutsideError, Unavailable
from hiro_extension_kit.extension import ext
from hiro_extension_kit.testing import FakeCore


class DictStore:
    """An app's own store, as CodeHiro's reports.db: plain get and put, "" taking a key away."""

    def __init__(self, **kept: str) -> None:
        self.kept = dict(kept)

    def get(self, key: str) -> str:
        return self.kept.get(key, "")

    def put(self, key: str, value: str) -> None:
        if value:
            self.kept[key] = value
        else:
            self.kept.pop(key, None)


@pytest.fixture
def link(monkeypatch):
    """The app's link with its settings in a store of the test's own; put back as it was afterwards."""
    link = hiroleague.link
    monkeypatch.setattr(link, "settings", link.settings)
    monkeypatch.setattr(link, "admin_url_set", link.admin_url_set)
    monkeypatch.setattr(link, "site_url_set", link.site_url_set)
    yield link
    ExtensionClient.set_url(link.client, "")
    link.client.update_info(hiroleague.info_for(hiroleague.site_url_default()))


def test_a_store_of_its_own_is_read_at_once(link) -> None:
    store = DictStore(**{hiroleague.URL_KEY: "ws://127.0.0.1:18082", hiroleague.ADMIN_URL_KEY: "http://hiro.local",
                         hiroleague.SITE_URL_KEY: "http://testapp.hiro.local"})
    link.use_settings(store)
    status = link.status()
    assert (status["url"], status["admin_url"], status["site_url"]) == (
        "ws://127.0.0.1:18082", "http://hiro.local", "http://testapp.hiro.local")
    assert link.client._info.offers.shows[0].url == "http://testapp.hiro.local"  # declared with the address set


def test_settings_changed_are_kept_in_that_store(link) -> None:
    store = DictStore()
    link.use_settings(store)
    asyncio.run(link.set_url("ws://127.0.0.1:18082"))
    asyncio.run(link.set_admin_url("http://hiro.local/"))
    assert store.kept == {hiroleague.URL_KEY: "ws://127.0.0.1:18082", hiroleague.ADMIN_URL_KEY: "http://hiro.local"}
    asyncio.run(link.set_admin_url(""))  # back to the derived address: the key goes
    assert hiroleague.ADMIN_URL_KEY not in store.kept


def test_the_app_database_is_the_default(link) -> None:
    assert isinstance(hiroleague.HiroLeagueLink().settings, hiroleague.AppDatabase)
    db = hiroleague.AppDatabase()
    db.put("hiroleague_test_key", "x")
    assert db.get("hiroleague_test_key") == "x"
    db.put("hiroleague_test_key", "")
    assert db.get("hiroleague_test_key") == ""


# --- the site's roles ----------------------------------------------------------------------------------------------


def test_the_site_shows_to_every_role_by_default() -> None:
    assert hiroleague.info_for("http://testapp.hiro.local").offers.shows[0].roles == []


def test_the_site_shows_to_the_roles_named(monkeypatch) -> None:
    monkeypatch.setattr(extension, "_extension", dataclasses.replace(ext(), site_roles=("owner",)))
    assert hiroleague.info_for("http://testapp.hiro.local").offers.shows[0].roles == ["owner"]


# --- the one sign-in, as far as it talks to the core ---------------------------------------------------------------


def test_sign_in_and_out_go_to_the_core_known(link) -> None:
    link.use_settings(DictStore())
    assert one_sign_in.sign_in_url(link, "/x") is None  # no address known: nowhere to send the browser
    assert one_sign_in.sign_out_url(link) is None
    link.use_settings(DictStore(**{hiroleague.ADMIN_URL_KEY: "http://hiro.local"}))
    assert one_sign_in.sign_in_url(link, "//evil.example") == "http://hiro.local/sign-in?for=test&next=%2F"
    assert one_sign_in.sign_out_url(link) == "http://hiro.local/api/auth/sign-out?for=test"
    assert one_sign_in.after_core_sign_out(link, "http://hiro.local/sign-in") == "http://hiro.local/sign-in"
    assert one_sign_in.after_core_sign_out(link, "https://evil.example/") == "/"


@pytest.fixture
def core(monkeypatch):
    fake = FakeCore()
    monkeypatch.setattr(ExtensionClient, "connected", property(lambda _self: fake.connected))
    monkeypatch.setattr(hiroleague.link.client, "request", fake.request)
    return fake


def test_a_code_is_redeemed(core) -> None:
    core.answers["auth.code"] = {"person_id": "p1", "name": "Michel", "role_id": "owner", "role_name": "Owner"}
    assert asyncio.run(one_sign_in.redeem(hiroleague.link, "123"))["person_id"] == "p1"


@pytest.mark.parametrize(("answer", "error"), [
    (ExtensionRequestError("invalid_code", "no such code"), Invalid),
    (ExtensionRequestError("timeout", "no answer"), Unavailable),
    (ExtensionRequestError("failed", "boom"), OutsideError),
    ({"name": "no id"}, OutsideError),
])
def test_a_code_the_core_refuses_or_garbles(core, answer, error) -> None:
    core.answers["auth.code"] = answer
    with pytest.raises(error):
        asyncio.run(one_sign_in.redeem(hiroleague.link, "123"))


def test_no_code_or_no_core(core) -> None:
    with pytest.raises(Invalid):
        asyncio.run(one_sign_in.redeem(hiroleague.link, ""))
    core.connected = False
    with pytest.raises(Unavailable):
        asyncio.run(one_sign_in.redeem(hiroleague.link, "123"))
