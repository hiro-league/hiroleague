"""Unit tests for ``PreferencesView`` (P7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.domain.preferences import DEFAULT_MAX_HISTORY_MESSAGES, WorkspacePreferences
from hirocli.runtime.agent_graph.preferences_view import PreferencesView
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime


def test_runtime_present_returns_runtime_current(tmp_path: Path) -> None:
    runtime = WorkspacePreferencesRuntime(tmp_path)
    runtime.update_many({"chat.max_messages": 12, "chat.cite_sources": True, "chat.instructions": "Be brief"})
    view = PreferencesView(runtime, tmp_path)

    assert view.current is not None
    assert view.history_window() == 12
    assert view.cite_sources() is True
    assert view.chat_instructions() == "Be brief"
    assert view.memory() is not None


def test_runtime_none_loads_from_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = WorkspacePreferences()
    loaded.chat.max_messages = 9
    monkeypatch.setattr(
        "hirocli.domain.preferences.load_preferences",
        lambda _path: loaded,
    )
    view = PreferencesView(None, tmp_path)

    assert view.history_window() == 9


def test_resolution_failure_returns_defaults(tmp_path: Path) -> None:
    class _BoomRuntime:
        @property
        def current(self):
            raise RuntimeError("boom")

    view = PreferencesView(_BoomRuntime(), tmp_path)

    assert view.current is None
    assert view.history_window() == DEFAULT_MAX_HISTORY_MESSAGES
    assert view.cite_sources() is False
    assert view.chat_instructions() == ""
    assert view.memory() is None


def test_runtime_none_calls_load_preferences(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Path] = []

    def _load(path: Path) -> WorkspacePreferences:
        calls.append(path)
        return WorkspacePreferences()

    monkeypatch.setattr(
        "hirocli.domain.preferences.load_preferences",
        _load,
    )
    view = PreferencesView(None, tmp_path)
    _ = view.current

    assert calls == [tmp_path]
