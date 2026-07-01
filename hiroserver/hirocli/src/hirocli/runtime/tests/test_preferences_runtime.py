from __future__ import annotations

import pytest
from pydantic import ValidationError

from hirocli.domain.preferences import WorkspacePreferences, load_preferences, save_preferences
from hirocli.runtime.preferences_runtime import PreferencePathError, WorkspacePreferencesRuntime


def test_runtime_reads_current_preferences_from_memory(tmp_path) -> None:
    runtime = WorkspacePreferencesRuntime(tmp_path)

    assert runtime.chat.max_messages == 6
    assert runtime.media.input.voice is True


def test_runtime_update_persists_and_updates_current_preferences(tmp_path) -> None:
    runtime = WorkspacePreferencesRuntime(tmp_path)

    updated = runtime.update("chat.max_messages", 8)

    assert updated.chat.max_messages == 8
    assert runtime.chat.max_messages == 8
    assert load_preferences(tmp_path).chat.max_messages == 8


def test_runtime_update_many_is_atomic_for_valid_edits(tmp_path) -> None:
    runtime = WorkspacePreferencesRuntime(tmp_path)

    updated = runtime.update_many(
        {
            "chat.max_messages": 9,
            "media.output.voice": True,
        }
    )

    assert updated.chat.max_messages == 9
    assert updated.media.output.voice is True
    persisted = load_preferences(tmp_path)
    assert persisted.chat.max_messages == 9
    assert persisted.media.output.voice is True


def test_runtime_update_allows_top_level_tuning_profiles(tmp_path) -> None:
    runtime = WorkspacePreferencesRuntime(tmp_path)
    profiles = runtime.current.tuning_profiles
    profiles["balanced_chat"].max_tokens = 1234

    updated = runtime.update("tuning_profiles", profiles)

    assert updated.tuning_profiles["balanced_chat"].max_tokens == 1234
    assert load_preferences(tmp_path).tuning_profiles["balanced_chat"].max_tokens == 1234


def test_runtime_rejects_subfield_write_into_write_whole_dict(tmp_path) -> None:
    """`tuning_profiles` is a whole-write dict: the schema walk descends by dict key but not into the
    profile MODEL, so a per-leaf write (`...balanced_chat.temperature`) is rejected rather than
    silently applied. This is the backend half of the `writeWhole` contract the admin save honors."""
    runtime = WorkspacePreferencesRuntime(tmp_path)

    with pytest.raises(PreferencePathError):
        runtime.update("tuning_profiles.balanced_chat.temperature", 0.5)

    assert runtime.current.tuning_profiles["balanced_chat"].temperature != 0.5


def test_runtime_rejects_readonly_computed_path(tmp_path) -> None:
    """Computed read-only enrichments (e.g. `knowledge.answering.model_resolved`) aren't persisted
    model fields, so a PATCH that targets one is rejected as an unknown path — the `readOnly` flag on
    those fields can never be written through, matching the admin save policy."""
    runtime = WorkspacePreferencesRuntime(tmp_path)

    with pytest.raises(PreferencePathError):
        runtime.update("knowledge.answering.model_resolved", "openai:gpt-4")


def test_runtime_update_rejects_unknown_path(tmp_path) -> None:
    runtime = WorkspacePreferencesRuntime(tmp_path)

    with pytest.raises(PreferencePathError):
        runtime.update("memory.not_real", 8)

    assert runtime.chat.max_messages == 6
    assert load_preferences(tmp_path).chat.max_messages == 6


def test_runtime_update_rejects_invalid_value(tmp_path) -> None:
    runtime = WorkspacePreferencesRuntime(tmp_path)

    with pytest.raises(ValidationError):
        runtime.update("chat.max_messages", 0)

    assert runtime.chat.max_messages == 6
    assert load_preferences(tmp_path).chat.max_messages == 6


def test_existing_preferences_without_chat_max_messages_default_to_six(tmp_path) -> None:
    path = tmp_path / "preferences.json"
    path.write_text(
        '{"version":2,"llm":{},"media":{"input":{"voice":true},"output":{}},"memory":{}}',
        encoding="utf-8",
    )

    runtime = WorkspacePreferencesRuntime(tmp_path)

    assert runtime.chat.max_messages == 6


def test_runtime_update_migrates_saved_version_to_current_schema(tmp_path) -> None:
    prefs = WorkspacePreferences(version=2)
    save_preferences(tmp_path, prefs)
    runtime = WorkspacePreferencesRuntime(tmp_path)

    runtime.update("chat.max_messages", 7)

    assert load_preferences(tmp_path).version == 3
