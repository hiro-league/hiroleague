"""Phase 7a Part B: importing HomeHiro's LLM profiles from a small homehiro.db built here with its columns."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from hirocli.domain.credential_store import CredentialStore
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime
from hirocli.services.ai_ask.import_homehiro import apply_plan, read_plan

# HomeHiro's tables (SQLModel names: the class name lower-cased), with the columns models.py declares.
SCHEMA = """
CREATE TABLE llmprofile (id TEXT PRIMARY KEY, name TEXT UNIQUE, provider TEXT, model TEXT, thinking TEXT,
    instructions TEXT, max_cost_day FLOAT, max_per_hour INTEGER, at_once INTEGER, fallback_id TEXT,
    created_at DATETIME, updated_at DATETIME);
CREATE TABLE llmdefault (use TEXT PRIMARY KEY, profile_id TEXT);
CREATE TABLE llmserver (id TEXT PRIMARY KEY, name TEXT UNIQUE, kind TEXT, address TEXT, models JSON,
    item_id INTEGER, alert_id INTEGER, created_at DATETIME, updated_at DATETIME);
CREATE TABLE automationgraph (id TEXT PRIMARY KEY, kind TEXT, name TEXT, about TEXT, params JSON, returns JSON,
    pure BOOLEAN, emits JSON, nodes JSON, edges JSON, builtin BOOLEAN, updated_at DATETIME);
"""
NOW = "2026-11-01 10:00:00"


def _db(tmp_path: Path) -> Path:
    path = tmp_path / "homehiro.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    profiles = [
        ("a1", "Camera questions", "gemini", "gemini-3.8-flash", "low", "Picture only.", 1.0, 0, 2, "b2"),
        ("b2", "Camera on Codex", "codex_cli", "gpt-6.1-sol", "medium", "", 0.0, 30, 1, "c3"),
        ("c3", "Local vision", "local:s1", "qwen3-vl-8b", "on", "", 0.0, 60, 1, None),
        ("d4", "Homework", "claude_cli", "sonnet", "max", "", 0.0, 10, 1, "zz"),
        ("e5", "Old model", "gemini", "gemini-1.0-gone", "low", "", 0.0, 0, 1, None),
    ]
    conn.executemany(
        "INSERT INTO llmprofile VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [(*p, NOW, NOW) for p in profiles]
    )
    conn.executemany("INSERT INTO llmdefault VALUES (?, ?)", [("ask", "a1"), ("study", "d4"), ("sites", "e5")])
    conn.executemany(
        "INSERT INTO llmserver VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?)",
        [("s1", "MrBeast", "lmstudio", "http://192.168.1.90:1234/", "{}", NOW, NOW),
         ("s2", "Laptop", "lmstudio", "http://192.168.1.50:1234", "{}", NOW, NOW)],
    )
    nodes = [{"id": "l1", "data": {"def": "llm", "props": {"model": "gemini-3.5-flash-lite"}}}]
    conn.execute(
        "INSERT INTO automationgraph VALUES ('g1', 'template', 'Welcome', '', '[]', '[]', 0, '[]', ?, '[]', 0, ?)",
        (json.dumps(nodes), NOW),
    )
    conn.commit()
    conn.close()
    return path


def test_the_plan_maps_profiles_uses_and_servers(tmp_path: Path) -> None:
    plan = read_plan(_db(tmp_path))
    # Ids exactly hh-<HomeHiro's id>: HomeHiro's copies send their saved profile id that way.
    assert set(plan.profiles) == {"hh-a1", "hh-b2", "hh-c3", "hh-d4", "hh-write-text"}
    a1, b2, c3, d4 = (plan.profiles[f"hh-{i}"] for i in ("a1", "b2", "c3", "d4"))
    assert (a1["label"], a1["model"], a1["max_cost_day"], a1["at_once"], a1["fallback"]) == (
        "Camera questions", "google:gemini-3.8-flash", 1.0, 2, "hh-b2",
    )
    assert (b2["model"], b2["max_per_hour"], b2["max_cost_day"], b2["fallback"]) == ("codex:gpt-6.1-sol", 30, None, "hh-c3")
    assert (c3["model"], c3["thinking"]) == ("lm_studio:qwen3-vl-8b", "medium")  # "on" → medium
    assert (d4["model"], d4["thinking"], d4["fallback"]) == ("claude_code:sonnet", "high", None)  # max → high; lost fallback
    # A model the catalog doesn't have is left out, with a note, and its use gets no profile.
    assert any("Old model" in n for n in plan.notes) and "home:sites" not in plan.uses
    assert plan.uses == {"home:ask": "hh-a1", "home:study": "hh-d4", "home:write": "hh-write-text"}
    assert plan.profiles["hh-write-text"]["model"] == "google:gemini-3.5-flash-lite"
    # One address per kind: the first kept, the other noted.
    assert plan.servers == {"lm_studio": "http://192.168.1.90:1234"}
    assert any("Laptop" in n for n in plan.notes)


def test_applying_writes_valid_preferences_and_the_address(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    plan = read_plan(_db(tmp_path))
    apply_plan(workspace, plan, workspace_id="test-ws")
    prefs = WorkspacePreferencesRuntime(workspace).current
    assert prefs.ai.profiles["hh-a1"].fallback == "hh-b2"
    assert prefs.ai.uses["home:ask"] == "hh-a1"
    cred = CredentialStore(workspace, "test-ws").get("lm_studio")
    assert cred is not None and cred.base_url == "http://192.168.1.90:1234"
    assert plan.written
