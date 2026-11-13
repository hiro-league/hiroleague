"""The app switcher's list (hiroleague.py `apps_for`): the apps one person may open, as the core answers sites.list,
HiroLeague first for a role that opens its settings, the app it is shown in marked `here`."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from hiro_channel_sdk import ExtensionRequestError
from hiro_channel_sdk.constants import METHOD_SITES_LIST

from hiro_extension_kit import hiroleague
from hiro_extension_kit.auth.guard import KIT_RULES
from hiro_extension_kit.errors import OutsideError, Unavailable

NET = {"extension": "net", "title": "Network", "icon": "network", "url": "http://net.hiro.local", "online": True}
HOME = {"extension": "home", "title": "Home", "icon": "house", "url": "http://home.hiro.local", "online": False}


class FakeClient:
    def __init__(self, answer: dict[str, Any] | Exception, connected: bool = True) -> None:
        self.answer = answer
        self.connected = connected
        self.asked: list[tuple[str, dict[str, Any]]] = []
        self.status_detail: dict[str, Any] = {}
        self.url = "ws://127.0.0.1:18082"

    async def request(self, method: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.asked.append((method, params))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def link(monkeypatch: pytest.MonkeyPatch):
    me = SimpleNamespace(name="net", site_title="Network", site_icon="network", site_default="http://net.hiro.local")
    monkeypatch.setattr(hiroleague, "ext", lambda: me)
    the_link = hiroleague.HiroLeagueLink.__new__(hiroleague.HiroLeagueLink)
    the_link.admin_url_set = "http://hiro.local"
    the_link.site_url_set = "http://net.hiro.local"
    return the_link


def _apps(link, client: FakeClient, person_id: str = "p1") -> list[dict[str, Any]]:
    link.client = client
    return asyncio.run(link.apps_for(person_id))


def test_an_owner_sees_hiroleague_first_and_this_app_marked_here(link):
    client = FakeClient({"apps": [HOME, NET], "opens_settings": True})
    apps = _apps(link, client)
    assert client.asked == [(METHOD_SITES_LIST, {"person_id": "p1"})]
    assert [(a["extension"], a["here"]) for a in apps] == [("hiroleague", False), ("home", False), ("net", True)]
    assert apps[0]["url"] == "http://hiro.local" and apps[1]["online"] is False


def test_a_role_that_doesnt_open_the_settings_sees_only_the_apps(link):
    apps = _apps(link, FakeClient({"apps": [NET], "opens_settings": False}))
    assert [a["extension"] for a in apps] == ["net"]


def test_this_app_shows_even_before_its_site_is_declared(link):
    apps = _apps(link, FakeClient({"apps": [HOME], "opens_settings": False}))
    assert [(a["extension"], a["here"]) for a in apps] == [("net", True), ("home", False)]


def test_sign_in_off_lists_only_this_app_without_asking(link):
    client = FakeClient({"apps": [HOME], "opens_settings": True})
    assert [a["extension"] for a in _apps(link, client, person_id="dev")] == ["net"]
    assert client.asked == []


def test_the_core_away_or_failing_says_why(link):
    with pytest.raises(Unavailable):
        _apps(link, FakeClient({}, connected=False))
    with pytest.raises(Unavailable):
        _apps(link, FakeClient(ExtensionRequestError("timeout", "no answer")))
    with pytest.raises(OutsideError, match="method_not_found"):
        _apps(link, FakeClient(ExtensionRequestError("method_not_found", "unknown method")))
    with pytest.raises(OutsideError, match="can't be read"):
        _apps(link, FakeClient({"apps": [{"title": "no name"}], "opens_settings": True}))


def test_anyone_with_a_role_may_ask():
    assert [(r.path, r.who) for r in KIT_RULES] == [("/api/apps", "signed_in")]
