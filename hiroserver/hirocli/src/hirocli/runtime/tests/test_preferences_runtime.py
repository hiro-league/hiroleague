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


def test_runtime_update_allows_whole_write_dict(tmp_path) -> None:
    # (Was tuning_profiles, removed in Phase 7b step 5; answer_prompts is the remaining writeWhole dict.)
    runtime = WorkspacePreferencesRuntime(tmp_path)
    prompts = runtime.current.graph.eval.answer_prompts
    prompts["mine"] = prompts["default"].model_copy(update={"label": "Mine", "locked": False, "prompt": "x"})

    updated = runtime.update("graph.eval.answer_prompts", prompts)

    assert updated.graph.eval.answer_prompts["mine"].prompt == "x"
    assert load_preferences(tmp_path).graph.eval.answer_prompts["mine"].prompt == "x"


def test_runtime_rejects_subfield_write_into_write_whole_dict(tmp_path) -> None:
    """A whole-write dict: the schema walk descends by dict key but not into the profile MODEL, so a
    per-leaf write is rejected rather than silently applied. This is the backend half of the
    `writeWhole` contract the admin save honors."""
    runtime = WorkspacePreferencesRuntime(tmp_path)

    with pytest.raises(PreferencePathError):
        runtime.update("graph.eval.answer_prompts.default.prompt", "nope")

    assert runtime.current.graph.eval.answer_prompts["default"].prompt != "nope"


def test_runtime_job_profile_round_trip(tmp_path) -> None:
    # Phase 7b step 5: an AI profile written by path, a job pointed at it, and deleting it refused
    # while the job still uses it.
    runtime = WorkspacePreferencesRuntime(tmp_path)
    updated = runtime.update_many(
        {"ai.profiles.p1": {"label": "P1", "model": "openai:gpt-6-luna"}, "llm.chat_profile": "p1"}
    )
    assert updated.llm.chat_profile == "p1"
    assert load_preferences(tmp_path).llm.chat_profile == "p1"
    with pytest.raises(Exception, match="unknown AI profile"):
        runtime.update("ai.profiles", {})


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

    assert load_preferences(tmp_path).version == 4
