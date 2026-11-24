"""Apps' LAN names (docs/site-names-design.md): the name rules, taken names, Caddy's file, and claiming."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hirocli.domain.events import DomainEvent, DomainEventType
from hirocli.domain.site_names import (
    CORE_ID,
    SiteName,
    SiteNameError,
    caddy_names,
    check_name,
    claim,
    core_names,
    gateway_name,
    list_claims,
    release,
    render_caddy,
    served,
)
from hirocli.runtime import site_names as runtime
from hirocli.runtime.request_handler import RequestRefused

CADDYFILE = """{
\tauto_https off
\tadmin off
}

http://adguard.local {
\treverse_proxy 127.0.0.1:3001
}

http://homehiro.local, http://Other.Local:80 {
\treverse_proxy 127.0.0.1:8100 {
\t\tflush_interval -1 # SSE
\t}
}

http://192.168.1.10 {
\t@tv path /tv
\thandle @tv {
\t\treverse_proxy 127.0.0.1:8100
\t}
\trespond 404
}

import sites/*.caddy
"""


def test_names_are_a_subdomain_of_hiro_local_or_one_word_local() -> None:
    assert check_name("Reports.Hiro.Local") == "reports.hiro.local"
    assert check_name("abc.local") == "abc.local"
    for bad in ("reports", "a.b.local", "-x.local", "x_y.local", "reports.hiro.com", "", "x..local"):
        with pytest.raises(SiteNameError) as caught:
            check_name(bad)
        assert caught.value.code == "invalid", bad


def test_the_hand_written_caddyfile_names_are_read(tmp_path: Path) -> None:
    f = tmp_path / "Caddyfile"
    f.write_text(CADDYFILE, encoding="utf-8")
    assert caddy_names(f) == {"adguard.local", "homehiro.local", "other.local", "192.168.1.10"}
    assert caddy_names(tmp_path / "missing") == set()


def test_caddys_file_proxies_each_name_to_its_port() -> None:
    text = render_caddy([SiteName("reports.hiro.local", "e2", 8120), SiteName("home.hiro.local", "e1", 8100)])
    assert text.index("http://home.hiro.local {") < text.index("http://reports.hiro.local {")
    assert "\treverse_proxy 127.0.0.1:8120 {" in text and "flush_interval -1" in text


def test_one_name_per_app_and_never_someone_elses(tmp_path: Path) -> None:
    kept, old = claim(tmp_path, "ext-reports", "reports.local", 8120, set())
    assert (kept.name, old) == ("reports.local", None)
    kept, old = claim(tmp_path, "ext-reports", "reports.hiro.local", 8120, set())
    assert (kept.name, old) == ("reports.hiro.local", "reports.local")
    assert [c.name for c in list_claims(tmp_path)] == ["reports.hiro.local"]

    with pytest.raises(SiteNameError) as caught:
        claim(tmp_path, "ext-home", "reports.hiro.local", 8100, set())
    assert caught.value.code == "taken"
    for taken in ("homehiro.local", "hiro.local"):
        with pytest.raises(SiteNameError) as caught:
            claim(tmp_path, "ext-home", taken, 8100, {"homehiro.local"})
        assert caught.value.code == "taken", taken
    with pytest.raises(SiteNameError) as caught:
        claim(tmp_path, "ext-home", "home.hiro.local", 0, set())
    assert caught.value.code == "invalid"


class _Names(runtime.SiteNames):
    """SiteNames with avahi-publish and the reload command replaced by records."""

    def __init__(self, ctx: Any) -> None:
        super().__init__(ctx)
        self.published: list[str] = []
        self.reloads = 0

    async def _publish(self, name: str) -> None:
        self.published.append(name)
        await asyncio.Event().wait()

    async def _reload_caddy(self) -> tuple[bool, str]:
        self.reloads += 1
        return True, ""


def _ctx(tmp_path: Path, **cfg: Any) -> Any:
    config = SimpleNamespace(
        site_names_ip=cfg.get("ip", "192.168.1.10"),
        site_names_caddy_file=str(tmp_path / "sites" / "hiroleague.caddy"),
        site_names_caddy_main=str(tmp_path / "Caddyfile"),
        site_names_caddy_reload=["docker", "restart", "caddy"],
        admin_port=18083,
        gateway_url=cfg.get("gateway_url", "ws://gate.hiro.local"),
        gateway_port=8765,
        gateway_builtin=cfg.get("gateway_builtin", True),
    )
    (tmp_path / "Caddyfile").write_text(cfg.get("caddyfile", CADDYFILE), encoding="utf-8")
    return SimpleNamespace(workspace_path=tmp_path, config=config)


def test_claiming_publishes_the_name_writes_caddy_and_drops_the_old_name(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runtime.shutil, "which", lambda _cmd: "/usr/bin/avahi-publish")

    async def go() -> None:
        names = _Names(_ctx(tmp_path))
        first = await names.claim("ext-reports", "reports.local", 8120)
        assert first == {"name": "reports.local", "url": "http://reports.local", "published": True, "proxied": True, "note": ""}
        second = await names.claim("ext-reports", "reports.hiro.local", 8120)
        assert second["url"] == "http://reports.hiro.local" and names.reloads == 2
        await asyncio.sleep(0)
        # The old name's publisher is stopped; the core's own two names are published beside the app's.
        assert set(names._publishers) == {"reports.hiro.local", "hiro.local", "gate.hiro.local"}
        caddy = (tmp_path / "sites" / "hiroleague.caddy").read_text(encoding="utf-8")
        assert "http://reports.hiro.local {" in caddy and "reports.local {" not in caddy.replace("reports.hiro.local", "")
        again = await names.claim("ext-reports", "reports.hiro.local", 8120)
        assert again["proxied"] is True and names.reloads == 2  # nothing changed: Caddy isn't restarted
        for task in names._publishers.values():
            task.cancel()

    asyncio.run(go())


def test_a_machine_not_set_up_keeps_the_claim_and_says_so(tmp_path: Path) -> None:
    async def go() -> dict[str, Any]:
        return await _Names(_ctx(tmp_path, ip="")).claim("ext-home", "home.hiro.local", 8100)

    answer = asyncio.run(go())
    assert answer["published"] is False and answer["proxied"] is False and "isn't set up" in answer["note"]
    assert [c.name for c in list_claims(tmp_path)] == ["home.hiro.local"]


def test_the_request_refuses_a_taken_name_with_its_reason(tmp_path: Path) -> None:
    names = _Names(_ctx(tmp_path))
    ctx = SimpleNamespace(
        msg=SimpleNamespace(routing=SimpleNamespace(sender_id="ext-home")),
        server_ctx=SimpleNamespace(site_names=names, extension_manager=None),
    )
    with pytest.raises(RequestRefused) as caught:
        asyncio.run(runtime.handle_sites_claim({"name": "homehiro.local", "port": 8100}, ctx))
    assert caught.value.code == "taken"


# ---------------------------------------------------------------------------
# The core's own names (Installing apps, phase 2)
# ---------------------------------------------------------------------------


def test_the_core_names_its_admin_and_the_gateway_it_runs() -> None:
    assert gateway_name("ws://gate.hiro.local") == "gate.hiro.local"
    assert gateway_name("WS://Gate.Hiro.Local:80/") == "gate.hiro.local"
    for not_a_name in ("ws://localhost:8765", "ws://192.168.1.10:8765", "wss://gate.example.com", "ws://hiro.local", ""):
        assert gateway_name(not_a_name) is None, not_a_name
    both = core_names(admin_port=18083, gateway_url="ws://gate.hiro.local", gateway_port=8765, gateway_builtin=True)
    assert both == [SiteName("hiro.local", CORE_ID, 18083), SiteName("gate.hiro.local", CORE_ID, 8765)]
    elsewhere = core_names(admin_port=18083, gateway_url="ws://gate.hiro.local", gateway_port=8765, gateway_builtin=False)
    assert [c.name for c in elsewhere] == ["hiro.local"]


def test_a_name_is_never_served_twice() -> None:
    core = [SiteName("hiro.local", CORE_ID, 18083), SiteName("gate.hiro.local", CORE_ID, 8765)]
    apps = [SiteName("home.hiro.local", "e1", 8100)]

    # The hand-written Caddyfile still serves hiro.local: the core leaves it there (Caddy refuses a name in two files).
    plan = served(apps, core, {"hiro.local", "adguard.local"})
    assert [c.name for c in plan.names] == ["home.hiro.local", "gate.hiro.local"]
    assert plan.deferred == {"hiro.local"} and plan.clashes == frozenset()

    # An app claimed gate.hiro.local before the core took its names: the app keeps it.
    plan = served([*apps, SiteName("gate.hiro.local", "e9", 9000)], core, set())
    assert [c.name for c in plan.names] == ["home.hiro.local", "gate.hiro.local", "hiro.local"]
    assert [c.extension_id for c in plan.names if c.name == "gate.hiro.local"] == ["e9"]
    assert plan.clashes == {"gate.hiro.local"}


def test_the_core_takes_its_names_once_the_hand_written_blocks_go(tmp_path: Path, monkeypatch, caplog) -> None:
    monkeypatch.setattr(runtime.shutil, "which", lambda _cmd: "/usr/bin/avahi-publish")
    caplog.set_level(logging.INFO)
    hand = CADDYFILE.replace("import sites", "http://hiro.local {\n\treverse_proxy 127.0.0.1:18083\n}\n\n"
                             "http://gate.hiro.local {\n\treverse_proxy 127.0.0.1:8765\n}\n\nimport sites")
    caddy = tmp_path / "sites" / "hiroleague.caddy"

    async def go() -> None:
        names = _Names(_ctx(tmp_path, caddyfile=hand))
        await names.claim("ext-home", "home.hiro.local", 8100)
        text = caddy.read_text(encoding="utf-8")
        assert "http://home.hiro.local {" in text and "hiro.local {" not in text.replace("home.hiro.local", "")
        assert set(names._publishers) == {"home.hiro.local"}
        # aicam's two blocks go: the next write takes both names, each once.
        (tmp_path / "Caddyfile").write_text(CADDYFILE, encoding="utf-8")
        await names.claim("ext-home", "home.hiro.local", 8100)
        text = caddy.read_text(encoding="utf-8")
        assert text.count("http://hiro.local {") == 1 and text.count("http://gate.hiro.local {") == 1
        assert "reverse_proxy 127.0.0.1:18083 {" in text and "reverse_proxy 127.0.0.1:8765 {" in text
        assert set(names._publishers) == {"home.hiro.local", "hiro.local", "gate.hiro.local"}
        for task in names._publishers.values():
            task.cancel()

    asyncio.run(go())
    said = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("hiro.local stays with the hand-written Caddyfile" in m for m in said)
    assert any("the core serves gate.hiro.local now" in m for m in said)


def test_no_app_may_claim_the_cores_names(tmp_path: Path) -> None:
    names = _Names(_ctx(tmp_path, gateway_builtin=False))  # a gateway run elsewhere: its name is still the devices'
    for taken in ("hiro.local", "gate.hiro.local"):
        with pytest.raises(SiteNameError) as caught:
            asyncio.run(names.claim("ext-home", taken, 8100))
        assert caught.value.code == "taken", taken


def test_a_removed_apps_name_stops_being_published_and_proxied(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runtime.shutil, "which", lambda _cmd: "/usr/bin/avahi-publish")
    caddy = tmp_path / "sites" / "hiroleague.caddy"

    async def go() -> None:
        names = _Names(_ctx(tmp_path))
        await names.claim("ext-home", "home.hiro.local", 8100)
        await names.claim("ext-net", "net.hiro.local", 8130)
        assert "home.hiro.local" in names._publishers
        # The removal tool gives the name back in the table, then says so on the bus.
        assert release(tmp_path, "ext-home") == "home.hiro.local"
        await names._on_extension_removed(DomainEvent(
            DomainEventType.EXTENSION_REMOVED, tmp_path,
            {"extension_id": "ext-home", "name": "home", "site_name": "home.hiro.local"},
        ))
        await asyncio.sleep(0)
        assert "home.hiro.local" not in names._publishers and "net.hiro.local" in names._publishers
        text = caddy.read_text(encoding="utf-8")
        assert "home.hiro.local" not in text and "http://net.hiro.local {" in text
        for task in names._publishers.values():
            task.cancel()

    asyncio.run(go())
