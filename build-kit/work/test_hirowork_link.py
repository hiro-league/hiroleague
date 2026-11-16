"""The hirowork: link: only up and down, an environment 0 to 5, and server names hiro-work knows."""

import pytest

import hirowork_link as link


@pytest.mark.parametrize("url, want", [
    ("hirowork:up/1", ("up", 1, [])),
    ("hirowork://down/0/", ("down", 0, [])),
    ("hirowork:up/2/homehiro-api,core", ("up", 2, ["homehiro-api", "core"])),
    ("hirowork:up/3/codehiro", ("up", 3, ["codehiro"])),
    ("hirowork:down/5/core-admin", ("down", 5, ["core-admin"])),
])
def test_a_known_command_passes(url, want):
    assert link.parse(url) == want


@pytest.mark.parametrize("url", [
    "hirowork:train/0", "hirowork:up/6", "hirowork:up/1/nope", "hirowork:up/1/core;calc", "hirowork:up/1/../x",
    "hirowork:status", "https://example.com", "hirowork:up/1/core&calc",
])
def test_anything_else_is_refused(url):
    with pytest.raises(link.Refused):
        link.parse(url)


def test_a_refused_link_runs_nothing_and_is_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(link, "LOG", tmp_path / "link.log")
    started = []
    monkeypatch.setattr(link.subprocess, "Popen", lambda *a, **k: started.append(a))
    assert link.run("hirowork:train/0") == 1 and not started
    assert "refused" in (tmp_path / "link.log").read_text(encoding="utf-8")
    assert link.run("hirowork:up/1/core") == 0
    [(cmd,)] = started
    assert cmd[cmd.index("cmd") + 2:cmd.index("&")] == [str(link.LAUNCHER), "up", "1", "core"]
