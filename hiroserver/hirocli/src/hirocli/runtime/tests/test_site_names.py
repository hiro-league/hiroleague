"""Every name the core serves (docs/site-names-design.md): the rules, the two tables, the front door's whole
configuration, and serving it: announced on the LAN and loaded into a fake Caddy's admin API."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hirocli.domain.events import DomainEvent, DomainEventType
from hirocli.domain.extensions import add_paired_extension
from hirocli.domain.front_door import FrontDoorAddressError, initial_config, parse_admin, render
from hirocli.domain.site_names import (
    CORE_ID,
    OTHER_ID,
    OtherSite,
    Site,
    SiteName,
    SiteNameError,
    add_extra,
    add_other_site,
    check_name,
    check_paths,
    check_site_name,
    check_target,
    claim,
    core_names,
    gateway_name,
    list_claims,
    list_other_sites,
    release,
    remove_site,
    served,
)
from hirocli.runtime import site_names as runtime
from hirocli.runtime.front_door import FrontDoor
from hirocli.runtime.request_handler import RequestRefused
from hirocli.tools import sites as sites_tools

CORE = [SiteName("hiro.local", CORE_ID, 18083), SiteName("gate.hiro.local", CORE_ID, 8765)]

# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


def test_names_are_a_subdomain_of_hiro_local_or_one_word_local() -> None:
    assert check_name("Reports.Hiro.Local") == "reports.hiro.local"
    assert check_name("abc.local") == "abc.local"
    for bad in ("reports", "a.b.local", "-x.local", "x_y.local", "reports.hiro.com", "", "x..local"):
        with pytest.raises(SiteNameError) as caught:
            check_name(bad)
        assert caught.value.code == "invalid", bad


def test_a_site_is_a_local_name_or_the_machines_address_sent_to_a_port_here() -> None:
    assert check_site_name("AdGuard.local") == "adguard.local"
    assert check_site_name("192.168.1.10") == "192.168.1.10"
    assert check_target("3001") == "127.0.0.1:3001"
    assert check_target("127.0.0.1:8100") == "127.0.0.1:8100"
    assert check_paths(["/tv", "/_app/*", "/tv"]) == ("/tv", "/_app/*")
    for bad_name in ("::1", "adguard", "a.b.c.local"):
        with pytest.raises(SiteNameError):
            check_site_name(bad_name)
    for bad_target in ("", "0", "70000", "host:", "a b:80"):
        with pytest.raises(SiteNameError):
            check_target(bad_target)
    for bad_path in ("tv", "/a b", "/x//y", "/*/x"):
        with pytest.raises(SiteNameError):
            check_paths([bad_path])


def test_the_core_names_its_admin_and_the_gateway_it_runs() -> None:
    assert gateway_name("ws://gate.hiro.local") == "gate.hiro.local"
    assert gateway_name("WS://Gate.Hiro.Local:80/") == "gate.hiro.local"
    for not_a_name in ("ws://localhost:8765", "ws://192.168.1.10:8765", "wss://gate.example.com", "ws://hiro.local", ""):
        assert gateway_name(not_a_name) is None, not_a_name
    both = core_names(admin_port=18083, gateway_url="ws://gate.hiro.local", gateway_port=8765, gateway_builtin=True)
    assert both == CORE
    elsewhere = core_names(admin_port=18083, gateway_url="ws://gate.hiro.local", gateway_port=8765, gateway_builtin=False)
    assert [c.name for c in elsewhere] == ["hiro.local"]


# ---------------------------------------------------------------------------
# The tables: an app's names, extra names, other sites
# ---------------------------------------------------------------------------


def test_one_main_name_per_app_and_never_someone_elses(tmp_path: Path) -> None:
    kept, old = claim(tmp_path, "ext-reports", "reports.local", 8120, set())
    assert (kept.name, old) == ("reports.local", None)
    kept, old = claim(tmp_path, "ext-reports", "reports.hiro.local", 8120, set())
    assert (kept.name, old) == ("reports.hiro.local", "reports.local")
    assert [c.name for c in list_claims(tmp_path)] == ["reports.hiro.local"]

    with pytest.raises(SiteNameError) as caught:
        claim(tmp_path, "ext-home", "reports.hiro.local", 8100, set())
    assert caught.value.code == "taken"
    for taken in ("gate.hiro.local", "hiro.local"):
        with pytest.raises(SiteNameError) as caught:
            claim(tmp_path, "ext-home", taken, 8100, {"gate.hiro.local"})
        assert caught.value.code == "taken", taken
    with pytest.raises(SiteNameError) as caught:
        claim(tmp_path, "ext-home", "home.hiro.local", 0, set())
    assert caught.value.code == "invalid"


def test_an_extra_name_follows_its_app_and_goes_with_it(tmp_path: Path) -> None:
    with pytest.raises(SiteNameError) as caught:
        add_extra(tmp_path, "ext-home", "homehiro.local", set())  # no main name yet
    assert caught.value.code == "invalid"
    claim(tmp_path, "ext-home", "home.hiro.local", 8100, set())
    extra = add_extra(tmp_path, "ext-home", "HomeHiro.local", set())
    assert (extra.name, extra.port, extra.extra) == ("homehiro.local", 8100, True)

    # A new main name keeps the extra one, which follows the new port; nobody else claims it.
    claim(tmp_path, "ext-home", "house.hiro.local", 8101, set())
    assert {(c.name, c.port, c.extra) for c in list_claims(tmp_path)} == {
        ("house.hiro.local", 8101, False), ("homehiro.local", 8101, True),
    }
    for who, name in (("ext-net", "homehiro.local"), ("ext-home", "homehiro.local")):
        with pytest.raises(SiteNameError) as caught:
            claim(tmp_path, who, name, 8130, set())
        assert caught.value.code == "taken", who

    # The app's own name is the app's: only the extra one is the owner's to drop.
    with pytest.raises(SiteNameError) as caught:
        remove_site(tmp_path, "house.hiro.local")
    assert caught.value.code == "invalid"
    assert remove_site(tmp_path, "homehiro.local") == "extra"
    add_extra(tmp_path, "ext-home", "homehiro.local", set())
    assert release(tmp_path, "ext-home") == "house.hiro.local"
    assert list_claims(tmp_path) == []


def test_an_other_site_takes_a_free_name_and_says_where_it_goes(tmp_path: Path) -> None:
    claim(tmp_path, "ext-home", "home.hiro.local", 8100, set())
    tv = add_other_site(tmp_path, "192.168.1.10", "8100", ["/tv", "/_app/*"], set())
    assert (tv.target, tv.paths) == ("127.0.0.1:8100", ("/tv", "/_app/*"))
    frigate = add_other_site(tmp_path, "frigate.local", "", [], set())
    assert frigate.announce_only
    assert [s.name for s in list_other_sites(tmp_path)] == ["192.168.1.10", "frigate.local"]

    for name, target, paths in (("home.hiro.local", "1", []), ("frigate.local", "2", []), ("hiro.local", "3", [])):
        with pytest.raises(SiteNameError) as caught:
            add_other_site(tmp_path, name, target, paths, {"hiro.local"})
        assert caught.value.code == "taken", name
    for name, paths in (("10.0.0.1", []), ("tv.local", ["/tv"])):  # an address or paths need somewhere to go
        with pytest.raises(SiteNameError) as caught:
            add_other_site(tmp_path, name, "", paths, set())
        assert caught.value.code == "invalid", name
    with pytest.raises(SiteNameError) as caught:
        claim(tmp_path, "ext-cam", "frigate.local", 5000, set())
    assert caught.value.code == "taken"

    assert remove_site(tmp_path, "FRIGATE.local") == "site"
    with pytest.raises(SiteNameError) as caught:
        remove_site(tmp_path, "frigate.local")
    assert caught.value.code == "not_found"


def test_a_name_is_never_served_twice() -> None:
    apps = [SiteName("home.hiro.local", "e1", 8100), SiteName("homehiro.local", "e1", 8100, extra=True)]
    others = [OtherSite("192.168.1.10", "127.0.0.1:8100", ("/tv",)), OtherSite("frigate.local")]
    plan = served(apps, CORE, others)
    assert [(s.name, s.owner, s.upstream, s.announce) for s in plan.sites] == [
        ("home.hiro.local", "e1", "127.0.0.1:8100", True),
        ("homehiro.local", "e1", "127.0.0.1:8100", True),
        ("hiro.local", CORE_ID, "127.0.0.1:18083", True),
        ("gate.hiro.local", CORE_ID, "127.0.0.1:8765", True),
        ("192.168.1.10", OTHER_ID, "127.0.0.1:8100", False),  # an address isn't announced
        ("frigate.local", OTHER_ID, "", True),  # announced only
    ]
    assert plan.clashes == frozenset()

    # An app claimed gate.hiro.local before the core took its names: the app keeps it.
    plan = served([*apps, SiteName("gate.hiro.local", "e9", 9000)], CORE, [])
    assert [s.owner for s in plan.sites if s.name == "gate.hiro.local"] == ["e9"]
    assert plan.clashes == {"gate.hiro.local"}
    assert len({s.name for s in plan.sites}) == len(plan.sites)


# ---------------------------------------------------------------------------
# The front door's whole configuration
# ---------------------------------------------------------------------------


def test_the_admin_address_is_a_socket_or_a_loopback_port() -> None:
    sock = parse_admin("unix//run/hiro-caddy/admin.sock|0660")
    assert (sock.socket, sock.base_url) == ("/run/hiro-caddy/admin.sock", "http://localhost")
    port = parse_admin("127.0.0.1:18079")
    assert (port.host_port, port.base_url) == ("127.0.0.1:18079", "http://127.0.0.1:18079")
    for bad in ("", "0.0.0.0:2019", "192.168.1.10:2019", "unix/relative.sock", "127.0.0.1:x"):
        with pytest.raises(FrontDoorAddressError):
            parse_admin(bad)
    assert json.loads(initial_config(sock)) == {"admin": {"listen": "unix//run/hiro-caddy/admin.sock|0660"}}


def test_every_load_is_the_whole_configuration_with_its_admin_block() -> None:
    sites = [
        Site("home.hiro.local", "e1", "127.0.0.1:8100"),
        Site("frigate.local", OTHER_ID, ""),
        Site("192.168.1.10", OTHER_ID, "127.0.0.1:8100", ("/tv", "/_app/*"), announce=False),
    ]
    text = render(sites, parse_admin("unix//run/hiro-caddy/admin.sock|0660"))
    # A load without its admin block moves Caddy's API to localhost:2019 (Nov 25, 2026): every load carries it.
    assert "\tadmin unix//run/hiro-caddy/admin.sock|0660\n\tauto_https off\n}" in text
    assert "http_port" not in text and "default_bind" not in text
    assert text.index("http://192.168.1.10 {") < text.index("http://home.hiro.local {")
    assert "frigate.local" not in text  # announced only: no block
    assert "\t@paths path /tv /_app/*\n\thandle @paths {\n\t\treverse_proxy 127.0.0.1:8100 {" in text
    assert "\trespond 404\n}" in text
    # Any other name gets the page that says no app answers to it, with the way to the admin.
    tail = text[text.index("http:// {"):]
    assert "No app answers to this name" in tail and 'href="http://hiro.local"' in tail and "PAGE 404" in tail
    assert render(list(reversed(sites)), parse_admin("unix//run/hiro-caddy/admin.sock|0660")) == text

    elsewhere = render(sites, parse_admin("127.0.0.1:18079"), http_port=7548, bind="127.0.0.1")
    assert "\thttp_port 7548\n\tdefault_bind 127.0.0.1\n}" in elsewhere


# ---------------------------------------------------------------------------
# Serving: announced, and loaded into the front door (a fake Caddy admin API on port 0)
# ---------------------------------------------------------------------------


class _FakeCaddy:
    """A small real server speaking Caddy's admin API: POST /load answers 200, or 400 with Caddy's error shape."""

    def __init__(self) -> None:
        self.loads: list[tuple[str, str]] = []
        self.refuse = ""
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 — http.server's name
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8")
                fake.loads.append((self.headers.get("Content-Type") or "", body))
                if fake.refuse:
                    payload = json.dumps({"error": fake.refuse}).encode()
                    self.send_response(400)
                else:
                    payload = b""
                    self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.address = f"127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def caddy():
    fake = _FakeCaddy()
    yield fake
    fake.close()


class _Publisher:
    """Announces into a set (the LAN stays untouched)."""

    def __init__(self, ip: str) -> None:
        self.ip = ip
        self.note = ""
        self.names: set[str] = set()

    @property
    def announced(self) -> set[str]:
        return set(self.names)

    async def sync(self, names: set[str]) -> None:
        self.names = set(names)

    async def close(self) -> None:
        self.names.clear()


class _Names(runtime.SiteNames):
    def _publisher_for_ip(self) -> Any:
        if not self._ip():
            return None
        if self._publisher is None:
            self._publisher = _Publisher(self._ip())
        return self._publisher


def _ctx(tmp_path: Path, **cfg: Any) -> Any:
    config = SimpleNamespace(
        site_names_ip=cfg.get("ip", "192.168.1.10"),
        admin_port=18083,
        gateway_url=cfg.get("gateway_url", "ws://gate.hiro.local"),
        gateway_port=8765,
        gateway_builtin=cfg.get("gateway_builtin", True),
    )
    return SimpleNamespace(workspace_path=tmp_path, config=config)


def _names(tmp_path: Path, caddy: _FakeCaddy | None, **cfg: Any) -> _Names:
    if caddy is None:
        return _Names(_ctx(tmp_path, **cfg), door_note="This machine has no front door yet.")
    return _Names(_ctx(tmp_path, **cfg), front_door=FrontDoor(parse_admin(caddy.address)))


def test_claiming_announces_the_name_and_loads_the_front_door_once_per_change(tmp_path: Path, caddy) -> None:
    async def go() -> None:
        names = _names(tmp_path, caddy)
        first = await names.claim("ext-reports", "reports.local", 8120)
        assert first == {"name": "reports.local", "url": "http://reports.local", "published": True, "proxied": True,
                         "note": ""}
        second = await names.claim("ext-reports", "reports.hiro.local", 8120)
        assert second["proxied"] is True and len(caddy.loads) == 2
        # The old name is gone everywhere; the core's own two names are served beside the app's.
        assert names._publisher.names == {"reports.hiro.local", "hiro.local", "gate.hiro.local"}
        content_type, body = caddy.loads[-1]
        assert content_type == "text/caddyfile"
        assert "http://reports.hiro.local {" in body and "http://reports.local {" not in body
        assert f"\tadmin {caddy.address}\n" in body
        again = await names.claim("ext-reports", "reports.hiro.local", 8120)
        assert again["proxied"] is True and len(caddy.loads) == 2  # nothing changed: nothing loaded

    asyncio.run(go())


def test_caddy_refusing_keeps_the_claim_says_why_and_is_tried_again(tmp_path: Path, caddy, caplog) -> None:
    caplog.set_level(logging.INFO)
    caddy.refuse = "listen tcp :80: bind: address already in use"

    async def go() -> None:
        names = _names(tmp_path, caddy)
        answer = await names.claim("ext-home", "home.hiro.local", 8100)
        assert answer["published"] is True and answer["proxied"] is False
        assert "address already in use" in answer["note"]
        assert [c.name for c in list_claims(tmp_path)] == ["home.hiro.local"]
        await names.claim("ext-home", "home.hiro.local", 8100)  # still refused: said once
        caddy.refuse = ""
        async with names._lock:  # the retry loop's round
            await names._apply()
        assert names._door_failed == "" and len(caddy.loads) == 3

    asyncio.run(go())
    said = [(r.levelno, r.getMessage()) for r in caplog.records if r.name.endswith("SITE_NAMES")]
    assert sum(1 for level, m in said if level == logging.WARNING and "Caddy kept what it had" in m) == 1
    assert any("Caddy took the names again" in m for _, m in said)


def test_a_front_door_away_is_said_in_words(tmp_path: Path) -> None:
    async def go() -> dict[str, Any]:
        names = _Names(_ctx(tmp_path), front_door=FrontDoor(parse_admin("127.0.0.1:9")))  # nothing listens there
        return await names.claim("ext-home", "home.hiro.local", 8100)

    answer = asyncio.run(go())
    assert answer["proxied"] is False and "isn't answering" in answer["note"]


def test_a_machine_not_set_up_keeps_the_claim_and_says_so(tmp_path: Path) -> None:
    async def go() -> dict[str, Any]:
        return await _names(tmp_path, None, ip="").claim("ext-home", "home.hiro.local", 8100)

    answer = asyncio.run(go())
    assert answer["published"] is False and answer["proxied"] is False
    assert "isn't set up to announce" in answer["note"] and "no front door" in answer["note"]
    assert [c.name for c in list_claims(tmp_path)] == ["home.hiro.local"]


def test_the_request_refuses_a_taken_name_with_its_reason(tmp_path: Path) -> None:
    names = _names(tmp_path, None)
    ctx = SimpleNamespace(
        msg=SimpleNamespace(routing=SimpleNamespace(sender_id="ext-home")),
        server_ctx=SimpleNamespace(site_names=names, extension_manager=None),
    )
    with pytest.raises(RequestRefused) as caught:
        asyncio.run(runtime.handle_sites_claim({"name": "hiro.local", "port": 8100}, ctx))
    assert caught.value.code == "taken"


def test_no_app_may_claim_the_cores_names(tmp_path: Path) -> None:
    names = _names(tmp_path, None, gateway_builtin=False)  # a gateway run elsewhere: its name is still the devices'
    for taken in ("hiro.local", "gate.hiro.local"):
        with pytest.raises(SiteNameError) as caught:
            asyncio.run(names.claim("ext-home", taken, 8100))
        assert caught.value.code == "taken", taken


def test_a_removed_apps_names_and_a_changed_site_are_served_at_once(tmp_path: Path, caddy) -> None:
    async def go() -> None:
        names = _names(tmp_path, caddy)
        await names.claim("ext-home", "home.hiro.local", 8100)
        await names.claim("ext-net", "net.hiro.local", 8130)
        add_extra(tmp_path, "ext-home", "homehiro.local", set())
        add_other_site(tmp_path, "adguard.local", "3001", [], set())
        await names._on_change(DomainEvent(DomainEventType.SITES_CHANGED, tmp_path, {"name": "adguard.local"}))
        body = caddy.loads[-1][1]
        assert "http://homehiro.local {" in body and "http://adguard.local {" in body
        assert {"homehiro.local", "adguard.local"} <= names._publisher.names

        # The removal tool gives the names back in the table, then says so on the bus.
        assert release(tmp_path, "ext-home") == "home.hiro.local"
        await names._on_change(DomainEvent(
            DomainEventType.EXTENSION_REMOVED, tmp_path,
            {"extension_id": "ext-home", "name": "home", "site_name": "home.hiro.local"},
        ))
        body = caddy.loads[-1][1]
        assert "home.hiro.local" not in body and "homehiro.local" not in body and "http://net.hiro.local {" in body
        assert not {"home.hiro.local", "homehiro.local"} & names._publisher.names

        # Another workspace's change is not this core's.
        before = len(caddy.loads)
        await names._on_change(DomainEvent(DomainEventType.SITES_CHANGED, tmp_path / "other", {}))
        assert len(caddy.loads) == before

    asyncio.run(go())


# ---------------------------------------------------------------------------
# hiro sites (the tools)
# ---------------------------------------------------------------------------


def test_the_sites_tools_add_list_and_remove(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sites_tools, "_path", lambda _ws: tmp_path)
    monkeypatch.setattr(sites_tools, "load_config", lambda _p: _ctx(tmp_path).config)
    said: list[DomainEvent] = []
    monkeypatch.setattr(sites_tools, "get_domain_event_bus", lambda: SimpleNamespace(publish=said.append))
    home = add_paired_extension(tmp_path, name="home", public_key="pk-home", info={"name": "home"})
    claim(tmp_path, home.extension_id, "home.hiro.local", 8100, set())

    extra = sites_tools.SitesAddTool().execute("homehiro.local", app="home")
    assert (extra.kind, extra.target) == ("extra", "127.0.0.1:8100")
    tv = sites_tools.SitesAddTool().execute("192.168.1.10", target="8100", paths=["/tv"])
    assert (tv.kind, tv.paths) == ("site", ["/tv"])
    with pytest.raises(SiteNameError) as caught:
        sites_tools.SitesAddTool().execute("x.local", app="nobody")
    assert caught.value.code == "not_found"
    with pytest.raises(SiteNameError):
        sites_tools.SitesAddTool().execute("gate.hiro.local", target="1")  # the core's

    listed = {s["name"]: (s["kind"], s["owner"], s["announced"]) for s in sites_tools.SitesListTool().execute().sites}
    assert listed == {
        "home.hiro.local": ("app", "home", True), "homehiro.local": ("extra", "home", True),
        "hiro.local": ("core", CORE_ID, True), "gate.hiro.local": ("core", CORE_ID, True),
        "192.168.1.10": ("site", OTHER_ID, False),
    }
    assert sites_tools.SitesRemoveTool().execute("homehiro.local").kind == "extra"
    assert [(e.type, e.payload["change"]) for e in said] == [
        (DomainEventType.SITES_CHANGED, "added"), (DomainEventType.SITES_CHANGED, "added"),
        (DomainEventType.SITES_CHANGED, "removed"),
    ]
