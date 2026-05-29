"""Tests for PreferenceReactor — prefix matching, debounce, workspace filter."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from hirocli.domain.events import (
    DomainEvent,
    DomainEventType,
    get_domain_event_bus,
)
from hirocli.domain.preferences import (
    ChatPreferences,
    LLMPreferences,
    WorkspacePreferences,
    compute_effective_changes,
    save_preferences,
)
from hirocli.runtime.preference_reactor import (
    PreferenceReactor,
    _select_changes_for_prefix,
)
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime


@pytest_asyncio.fixture(autouse=True)
async def _bus_attached_to_loop():
    bus = get_domain_event_bus()
    bus.reset()
    bus.attach_loop(asyncio.get_running_loop())
    yield
    bus.reset()


def _publish(workspace_path: Path, changes: dict[str, tuple[object, object]]) -> None:
    get_domain_event_bus().publish(
        DomainEvent(
            type=DomainEventType.PREFERENCES_SAVED,
            workspace_path=workspace_path,
            payload={"prefs": object(), "effective_changes": dict(changes)},
        )
    )


# ---------------------------------------------------------------------------
# Pure prefix-match helper
# ---------------------------------------------------------------------------


def test_select_changes_exact_leaf_match() -> None:
    changes = {"llm.default_stt": (None, "openai:gpt-4o-transcribe")}
    assert _select_changes_for_prefix(changes, "llm.default_stt") == changes


def test_select_changes_below_prefix() -> None:
    changes = {
        "tuning_profiles.balanced_chat.temperature": (0.7, 0.4),
        "llm.default_chat": ("a", "b"),
    }
    assert _select_changes_for_prefix(changes, "tuning_profiles") == {
        "tuning_profiles.balanced_chat.temperature": (0.7, 0.4),
    }


def test_select_changes_above_prefix() -> None:
    """A whole-subtree replace at ``tuning_profiles`` matches a prefix below it."""
    changes = {"tuning_profiles": ({}, {"balanced_chat": {"temperature": 0.4}})}
    assert _select_changes_for_prefix(
        changes, "tuning_profiles.balanced_chat.temperature",
    ) == changes


def test_select_changes_unrelated_path() -> None:
    changes = {"media.input.voice": (True, False)}
    assert _select_changes_for_prefix(changes, "llm.default_stt") == {}


# ---------------------------------------------------------------------------
# compute_effective_changes
# ---------------------------------------------------------------------------


def test_compute_effective_changes_only_real_diffs() -> None:
    old = WorkspacePreferences(
        llm=LLMPreferences(default_stt="openai:gpt-4o-transcribe"),
        chat=ChatPreferences(max_messages=6),
    )
    new = WorkspacePreferences(
        llm=LLMPreferences(default_stt="openai:gpt-4o-mini-transcribe"),
        chat=ChatPreferences(max_messages=6),
    )
    changes = compute_effective_changes(old, new)
    assert changes == {
        "llm.default_stt": ("openai:gpt-4o-transcribe", "openai:gpt-4o-mini-transcribe"),
    }


def test_compute_effective_changes_no_op() -> None:
    prefs = WorkspacePreferences()
    assert compute_effective_changes(prefs, prefs) == {}


def test_compute_effective_changes_from_none_treats_all_leaves_as_new() -> None:
    new = WorkspacePreferences(chat=ChatPreferences(max_messages=9))
    changes = compute_effective_changes(None, new)
    assert ("chat.max_messages", (None, 9)) in changes.items()


# ---------------------------------------------------------------------------
# Reactor behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reaction_fires_for_matching_prefix(tmp_path: Path) -> None:
    received: list[dict[str, tuple[object, object]]] = []

    async def handler(_path: Path, changes: dict[str, tuple[object, object]]) -> None:
        received.append(dict(changes))

    reactor = PreferenceReactor(tmp_path)
    try:
        reactor.on_change("llm.default_stt", handler, key="t.stt", debounce_ms=10)
        _publish(tmp_path, {"llm.default_stt": ("a", "b")})
        await asyncio.sleep(0.08)
        assert received == [{"llm.default_stt": ("a", "b")}]
    finally:
        reactor.close()


@pytest.mark.asyncio
async def test_reaction_skipped_for_other_paths(tmp_path: Path) -> None:
    fired: list[dict[str, tuple[object, object]]] = []

    async def handler(_path: Path, changes: dict[str, tuple[object, object]]) -> None:
        fired.append(dict(changes))

    reactor = PreferenceReactor(tmp_path)
    try:
        reactor.on_change("llm.default_stt", handler, key="t.stt", debounce_ms=10)
        _publish(tmp_path, {"media.input.voice": (True, False)})
        await asyncio.sleep(0.05)
        assert fired == []
    finally:
        reactor.close()


@pytest.mark.asyncio
async def test_reaction_filters_by_workspace(tmp_path: Path) -> None:
    fired: list[Path] = []

    async def handler(path: Path, _changes: dict[str, tuple[object, object]]) -> None:
        fired.append(path)

    reactor = PreferenceReactor(tmp_path)
    try:
        reactor.on_change("llm.default_stt", handler, key="t.stt", debounce_ms=10)
        other = tmp_path / "other"
        other.mkdir()
        _publish(other, {"llm.default_stt": ("a", "b")})
        await asyncio.sleep(0.05)
        assert fired == []

        _publish(tmp_path, {"llm.default_stt": ("a", "b")})
        await asyncio.sleep(0.05)
        assert fired == [tmp_path]
    finally:
        reactor.close()


@pytest.mark.asyncio
async def test_reaction_debounces_burst(tmp_path: Path) -> None:
    calls: list[dict[str, tuple[object, object]]] = []

    async def handler(_path: Path, changes: dict[str, tuple[object, object]]) -> None:
        calls.append(dict(changes))

    reactor = PreferenceReactor(tmp_path)
    try:
        reactor.on_change("llm.default_stt", handler, key="t.stt", debounce_ms=80)
        _publish(tmp_path, {"llm.default_stt": ("a", "b")})
        _publish(tmp_path, {"llm.default_stt": ("b", "c")})
        _publish(tmp_path, {"llm.default_stt": ("c", "d")})
        await asyncio.sleep(0.2)
        assert len(calls) == 1
        # Latest write wins for the (old, new) tuple at the same path.
        assert calls[0]["llm.default_stt"] == ("c", "d")
    finally:
        reactor.close()


@pytest.mark.asyncio
async def test_reaction_skipped_when_no_effective_changes(tmp_path: Path) -> None:
    fired: list[dict[str, tuple[object, object]]] = []

    async def handler(_path: Path, changes: dict[str, tuple[object, object]]) -> None:
        fired.append(dict(changes))

    reactor = PreferenceReactor(tmp_path)
    try:
        reactor.on_change("llm.default_stt", handler, key="t.stt", debounce_ms=10)
        _publish(tmp_path, {})
        await asyncio.sleep(0.05)
        assert fired == []
    finally:
        reactor.close()


@pytest.mark.asyncio
async def test_handler_exception_does_not_break_subsequent_runs(tmp_path: Path) -> None:
    seen: list[str] = []

    async def handler(_path: Path, changes: dict[str, tuple[object, object]]) -> None:
        seen.append(next(iter(changes.values()))[1])
        if seen == ["b"]:
            raise RuntimeError("boom")

    reactor = PreferenceReactor(tmp_path)
    try:
        reactor.on_change("llm.default_stt", handler, key="t.stt", debounce_ms=10)
        _publish(tmp_path, {"llm.default_stt": ("a", "b")})
        await asyncio.sleep(0.05)
        _publish(tmp_path, {"llm.default_stt": ("b", "c")})
        await asyncio.sleep(0.05)
        assert seen == ["b", "c"]
    finally:
        reactor.close()


# ---------------------------------------------------------------------------
# Integration: save_preferences via runtime publishes effective_changes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runtime_update_publishes_effective_changes_only(tmp_path: Path) -> None:
    """A second update setting the same value must not republish that path."""
    save_preferences(
        tmp_path,
        WorkspacePreferences(chat=ChatPreferences(max_messages=6)),
    )

    runtime = WorkspacePreferencesRuntime(tmp_path)
    captured: list[dict[str, tuple[object, object]]] = []

    async def handler(_path: Path, changes: dict[str, tuple[object, object]]) -> None:
        captured.append(dict(changes))

    reactor = PreferenceReactor(tmp_path)
    try:
        reactor.on_change("chat.max_messages", handler, key="t.chat", debounce_ms=10)

        runtime.update("chat.max_messages", 9)
        await asyncio.sleep(0.05)
        assert captured == [{"chat.max_messages": (6, 9)}]

        runtime.update("chat.max_messages", 9)
        await asyncio.sleep(0.05)
        assert len(captured) == 1
    finally:
        reactor.close()
