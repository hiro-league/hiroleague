"""Phase 7b step 5 tools: Restore default on a job's AI profile, and characters naming profiles."""

from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.domain.preferences import load_preferences, save_preferences
from hirocli.domain.preferences.models import WorkspacePreferences
from hirocli.tools import ai as ai_tools
from hirocli.tools import character as character_tools
from hirocli.tools.ai import AiProfileRestoreDefaultTool
from hirocli.tools.character import CharacterCreateTool, CharacterUpdateTool


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(ai_tools, "_workspace", lambda workspace: ("w", tmp_path))
    monkeypatch.setattr(character_tools, "_resolve_path", lambda workspace: tmp_path)
    prefs = WorkspacePreferences.model_validate(
        {
            "ai": {
                "profiles": {
                    "hiro-chat": {
                        "label": "My chat", "model": "openai:gpt-6-luna", "preset": "chat", "temperature": 1.5,
                        "max_tokens": 50, "thinking": "high", "num_ctx": 999, "instructions": "Be odd.",
                        "max_cost_day": 2.0,
                    },
                    "mine": {"label": "Mine", "model": "openai:gpt-6-luna"},
                }
            },
            "voice": {"profiles": {"v1": {"label": "V1", "model": "openai:gpt-4o-mini-tts", "voice": "sage"}}},
            "llm": {"chat_profile": "hiro-chat"},
        }
    )
    save_preferences(tmp_path, prefs)
    return tmp_path


def test_restore_default_resets_tuning_and_keeps_model(workspace: Path) -> None:
    result = AiProfileRestoreDefaultTool().execute(profile_id="hiro-chat")

    assert result.preset == "chat"
    profile = load_preferences(workspace).ai.profiles["hiro-chat"]
    # The chat preset (0.3 / 2048 / thinking None), no context window, no instructions…
    assert (profile.temperature, profile.max_tokens, profile.thinking) == (0.3, 2048, None)
    assert (profile.num_ctx, profile.instructions) == (None, "")
    # …while the model, name and limits stay.
    assert (profile.model, profile.label, profile.max_cost_day) == ("openai:gpt-6-luna", "My chat", 2.0)


def test_restore_default_refuses_a_profile_that_isnt_a_jobs_default(workspace: Path) -> None:
    with pytest.raises(ValueError, match="isn't a job's default"):
        AiProfileRestoreDefaultTool().execute(profile_id="mine")
    with pytest.raises(ValueError, match="No AI profile"):
        AiProfileRestoreDefaultTool().execute(profile_id="ghost")


def test_character_names_existing_profiles_only(workspace: Path) -> None:
    with pytest.raises(ValueError, match='AI profile "ghost" doesn\'t exist'):
        CharacterCreateTool().execute(character_id="bot-one", name="Bot", ai_profiles_json='["ghost"]')

    created = CharacterCreateTool().execute(
        character_id="bot-one", name="Bot", ai_profiles_json='["mine"]', voice_profiles_json='["v1"]'
    )
    assert created.character["ai_profiles"] == ["mine"]
    assert created.character["voice_profiles"] == ["v1"]

    # "" leaves a list as it is; "[]" clears it.
    updated = CharacterUpdateTool().execute(character_id="bot-one", ai_profiles_json="", voice_profiles_json="[]")
    assert updated.character["ai_profiles"] == ["mine"]
    assert updated.character["voice_profiles"] == []
    with pytest.raises(ValueError, match='Voice profile "nope" doesn\'t exist'):
        CharacterUpdateTool().execute(character_id="bot-one", voice_profiles_json='["nope"]')
