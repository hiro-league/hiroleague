"""The PC's helper for CodeHiro's environment cards: only up and down, an environment 0 to 5, known server names."""

import pytest

import relay


@pytest.mark.parametrize("ask, want", [
    ({"verb": "up", "env": 1}, ("up", 1, [])),
    ({"verb": "down", "env": 0, "servers": []}, ("down", 0, [])),
    ({"verb": "up", "env": 2, "servers": ["homehiro-api", "core"]}, ("up", 2, ["homehiro-api", "core"])),
    ({"verb": "up", "env": 3, "servers": ["codehiro"]}, ("up", 3, ["codehiro"])),
    ({"verb": "down", "env": 5, "servers": ["core-admin"]}, ("down", 5, ["core-admin"])),
])
def test_a_known_ask_passes(ask, want):
    assert relay.check(ask) == want


@pytest.mark.parametrize("ask", [
    {"verb": "train", "env": 0}, {"verb": "up", "env": 6}, {"verb": "up", "env": "1"},
    {"verb": "up", "env": 1, "servers": ["nope"]}, {"verb": "up", "env": 1, "servers": ["core&calc"]},
    {"verb": "up", "env": 1, "servers": "core"}, {},
])
def test_anything_else_is_refused(ask):
    with pytest.raises(relay.Refused):
        relay.check(ask)


def test_a_refused_ask_runs_nothing_and_is_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(relay, "LOG", tmp_path / "relay.log")
    started = []
    monkeypatch.setattr(relay.subprocess, "Popen", lambda *a, **k: started.append(a))
    assert relay.run({"verb": "train", "env": 0}) is False and not started
    assert "refused" in (tmp_path / "relay.log").read_text(encoding="utf-8")
    assert relay.run({"verb": "up", "env": 1, "servers": ["core"]}) is True
    [(cmd,)] = started
    assert cmd[cmd.index("cmd") + 2:cmd.index("&")] == [str(relay.LAUNCHER), "up", "1", "core"]


def test_it_asks_codehiro_beside_the_events_it_sends():
    assert relay.URL.endswith("/api/work/asks/next")
