"""Apps' LAN names (docs/site-names-design.md): the name rules, taken names, Caddy's file, and claiming."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hirocli.domain.site_names import SiteName, SiteNameError, caddy_names, check_name, claim, list_claims, render_caddy
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
    )
    (tmp_path / "Caddyfile").write_text(CADDYFILE, encoding="utf-8")
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
        assert set(names._publishers) == {"reports.hiro.local"}  # the old name's publisher is stopped
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
