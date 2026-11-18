"""The PC's helper for CodeHiro's asks: up and down (an environment 0 to 5, known server names), and the doc audit."""

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


def test_changes_are_said_for_made_environments_only_when_they_differ(tmp_path, monkeypatch):
    monkeypatch.setattr(relay.hw, "ROOT", tmp_path)
    monkeypatch.setattr(relay.hw, "TASKS", tmp_path / "tasks")
    (tmp_path / "env2" / "hiroleague" / ".git").mkdir(parents=True)  # env2 is made; env1, env3 to env5 aren't
    found = {0: ["codehiro"], 2: []}
    left = {0: [], 2: []}
    monkeypatch.setattr(relay.hw, "changed_repos", lambda env, tasks: found[env])
    monkeypatch.setattr(relay.hw, "leftovers", lambda env, tasks: left[env])
    sent = []
    monkeypatch.setattr(relay.hw, "event", lambda **e: sent.append((e["env"], e["step"], e["repos"], e["leftovers"])))
    said = relay.changes({})
    assert sent == [(0, "changes", ["codehiro"], []), (2, "changes", [], [])]
    sent.clear()
    found[2] = ["homehiro"]
    said = relay.changes(said)
    assert sent == [(2, "changes", ["homehiro"], [])]  # env0 is as it was said
    sent.clear()
    left[2] = [{"repo": "nethiro", "what": "1 uncommitted file"}]
    relay.changes(said)
    assert sent == [(2, "changes", ["homehiro"], [{"repo": "nethiro", "what": "1 uncommitted file"}])]


def test_env0s_unlisted_files_are_said_when_they_change_and_its_sizes_every_hour(monkeypatch):
    found = [{"group": "homehiro", "names": ["tts-cache"]}]
    monkeypatch.setattr(relay.hw.data, "load", lambda root: {})
    monkeypatch.setattr(relay.hw.data, "survey", lambda hw, lists, place, measure=True: {
        "unlisted": list(found), **({"sizes": {"homehiro": {"homehiro.db": 5}}} if measure else {})})
    clock = [10_000.0]
    monkeypatch.setattr(relay.time, "monotonic", lambda: clock[0])
    sent = []
    monkeypatch.setattr(relay.hw, "event", lambda **e: sent.append((e["step"], e["place"], e["unlisted"], e["sizes"])))
    said, at = relay.drift(None, 0.0)
    assert sent == [("copy-lists", "env0", [{"group": "homehiro", "names": ["tts-cache"]}], {"homehiro": {"homehiro.db": 5}})]
    sent.clear()
    clock[0] += 600
    said, at = relay.drift(said, at)
    assert sent == []  # as it was said, and not an hour yet
    found.clear()
    said, at = relay.drift(said, at)
    assert [e[2] for e in sent] == [[]]  # listed now: said, so Sweep clears it
    sent.clear()
    clock[0] += 3600
    relay.drift(said, at)
    assert len(sent) == 1  # the hour's sizes


def test_it_asks_codehiro_beside_the_events_it_sends():
    assert relay.URL.endswith("/api/work/asks/next")


def test_the_audit_ask_opens_claude_on_the_skill_in_env0s_hiro_docs(tmp_path, monkeypatch):
    monkeypatch.setattr(relay, "LOG", tmp_path / "relay.log")
    started = []
    monkeypatch.setattr(relay.subprocess, "Popen", lambda *a, **k: started.append(a))
    assert relay.run({"verb": "audit", "env": 3, "servers": ["anything"]}) is True  # an audit ask takes nothing else
    [(cmd,)] = started
    assert cmd[cmd.index("-w") + 1] == "hiro-audit"
    assert cmd[cmd.index("-d") + 1] == str(relay.AUDIT_DIR) and relay.AUDIT_DIR.name == "hiro-docs"
    assert cmd[-3:] == ["/k", relay.claude(), "/hiro-doc-audit"]
