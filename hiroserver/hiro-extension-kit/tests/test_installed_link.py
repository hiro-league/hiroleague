"""An app the core installed (Installing apps, phase 5): it pairs from its install's environment, claims its name under
the core's own domain with its key's dashed form on the port it really listens on, derives the admin's address from
that domain, and answers `extension.setup` (hiroleague.py)."""

import asyncio
import dataclasses
import logging

import pytest
from hiro_channel_sdk import ExtensionClient, ExtensionCredentials
from hiro_channel_sdk.constants import ENV_CORE_URL, ENV_PAIRING_CODE, SITES_DOMAIN
from sqlmodel import Session

from hiro_extension_kit import hiroleague, identity, settings
from hiro_extension_kit.db import engine
from hiro_extension_kit.extension import SetupStep, ext
from hiro_extension_kit.testing import FakeCore


def claimed(params: dict) -> dict:
    return {"name": params["name"], "url": f"http://{params['name']}", "published": True, "proxied": True, "note": ""}


@pytest.fixture
def core(monkeypatch):
    """A fake core in place of the link's connection (as test_site_claim.py), the core named testpc."""
    fake = FakeCore()
    link = hiroleague.link
    monkeypatch.setattr(ExtensionClient, "connected", property(lambda _self: fake.connected))
    monkeypatch.setattr(link.client, "request", fake.request)
    monkeypatch.setattr(link.client, "set_url", lambda url: None)
    monkeypatch.setattr(link, "site_url_set", "")
    monkeypatch.setattr(link, "domain", "testpc.local")
    yield fake
    link.client.update_info(hiroleague.info_for(hiroleague.site_url_default()))


def published_key(monkeypatch, key: str) -> None:
    """The app's key as a publisher's (acme.weather): the kit's test app is otherwise `test`."""
    keyed = dataclasses.replace(ext(), name=key)
    monkeypatch.setattr(hiroleague, "ext", lambda: keyed)


def test_the_default_name_is_the_dashed_key_under_the_cores_domain_on_the_real_port(core, monkeypatch):
    published_key(monkeypatch, "acme.weather")
    monkeypatch.setenv(hiroleague.PORT_ENV, "7305")
    core.answers["sites.claim"] = claimed
    asyncio.run(hiroleague.link._claim_default())
    assert core.asked == [("sites.claim", {"name": "acme-weather.testpc.local", "port": 7305})]
    assert hiroleague.link.site_url() == "http://acme-weather.testpc.local"


def test_without_port_in_the_environment_the_declared_port_is_claimed(monkeypatch):
    monkeypatch.delenv(hiroleague.PORT_ENV, raising=False)
    assert hiroleague.listen_port() == ext().port
    monkeypatch.setenv(hiroleague.PORT_ENV, "not a port")
    assert hiroleague.listen_port() == ext().port


def test_the_cores_domain_comes_from_its_welcome() -> None:
    assert hiroleague.core_domain({"domain": "testpc.local"}) == "testpc.local"
    assert hiroleague.core_domain({"name": "hiroleague"}) == SITES_DOMAIN  # a core from before it said
    assert hiroleague.core_domain(None) == SITES_DOMAIN
    assert hiroleague.core_domain({"domain": "evil.example"}) == SITES_DOMAIN


def test_the_admin_on_the_same_machine_is_at_the_cores_own_name() -> None:
    assert hiroleague.derived_admin_url("ws://127.0.0.1:18082", 18080, "testpc.local") == "http://testpc.local"
    assert hiroleague.derived_admin_url("ws://192.168.1.10:18082", 18080, "testpc.local") == "http://192.168.1.10:18080"


def test_a_typed_subdomain_is_under_the_cores_domain(core):
    core.answers["sites.claim"] = claimed
    out = asyncio.run(hiroleague.link.claim_site_name("Home", "subdomain"))
    assert out["url"] == "http://home.testpc.local"
    assert (out["status"]["site_label"], out["status"]["site_kind"]) == ("home", "subdomain")


# --- pairing from the install's environment -----------------------------------------------------------------------


@pytest.fixture
def pairs(monkeypatch):
    """What the link's client was asked to pair with, its key folder empty, the client's URL as set."""
    asked: list[str] = []
    link = hiroleague.link
    monkeypatch.setattr(link.client, "pair", lambda code: asked.append(code))
    ExtensionCredentials(identity.app().data_dir / "hiroleague").forget()
    monkeypatch.setattr(link.client, "_url", "ws://127.0.0.1:18082")
    return asked


def test_an_unpaired_install_pairs_with_its_code_and_never_logs_it(pairs, monkeypatch, caplog):
    monkeypatch.setenv(ENV_PAIRING_CODE, " 482913 ")
    caplog.set_level(logging.INFO, logger=hiroleague.log.name)
    hiroleague.link._pair_from_install()
    assert pairs == ["482913"]
    assert "pairs with the code its install gave it" in caplog.text and "482913" not in caplog.text


def test_a_paired_app_or_one_without_a_core_never_uses_the_code(pairs, monkeypatch):
    monkeypatch.setenv(ENV_PAIRING_CODE, "482913")
    monkeypatch.setattr(ExtensionCredentials, "extension_id", lambda _self: "ext-1")
    hiroleague.link._pair_from_install()
    monkeypatch.undo()
    monkeypatch.setenv(ENV_PAIRING_CODE, "482913")
    monkeypatch.setattr(hiroleague.link.client, "_url", "")
    monkeypatch.setattr(hiroleague.link.client, "pair", lambda code: pairs.append(code))
    hiroleague.link._pair_from_install()
    assert pairs == []


def test_the_installs_core_address_is_taken_while_none_is_set(monkeypatch):
    link = hiroleague.link
    monkeypatch.setenv(ENV_CORE_URL, "ws://127.0.0.1:18082")
    monkeypatch.delenv(ENV_PAIRING_CODE, raising=False)

    async def no_run() -> None:
        return None

    monkeypatch.setattr(link.client, "run", no_run)
    monkeypatch.setattr(link.client, "set_url", lambda url: None)
    asyncio.run(link._connect())
    with Session(engine) as s:
        assert settings.get(s, hiroleague.URL_KEY) == "ws://127.0.0.1:18082"
        settings.put(s, hiroleague.URL_KEY, None)
        s.commit()


# --- extension.setup ---------------------------------------------------------------------------------------------


def test_setup_answers_each_step_with_its_check(monkeypatch, caplog):
    def broken() -> bool:
        raise RuntimeError("the database is away")

    steps = (SetupStep("ha", "Home Assistant's address", "/settings/ha", lambda: True),
             SetupStep("token", "Home Assistant's token", "/settings/ha", broken))
    keyed = dataclasses.replace(ext(), setup=steps)
    monkeypatch.setattr(hiroleague, "ext", lambda: keyed)
    answer = asyncio.run(hiroleague.link._setup({}))
    assert answer == {"items": [
        {"id": "ha", "title": "Home Assistant's address", "done": True, "link": {"app": "test", "path": "/settings/ha"}},
        {"id": "token", "title": "Home Assistant's token", "done": False, "link": {"app": "test", "path": "/settings/ha"}},
    ]}
    assert "checking whether \"Home Assistant's token\" is set" in caplog.text


def test_an_app_with_nothing_to_set_answers_no_items() -> None:
    assert asyncio.run(hiroleague.link._setup({})) == {"items": []}
