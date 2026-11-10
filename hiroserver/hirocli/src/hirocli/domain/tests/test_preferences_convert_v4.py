"""The one-time preferences v3 → v4 conversion (Phase 7b step 5: AI profiles for Hiro's jobs).

Uses the real model catalog: the converted profiles are validated against it like any other.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hirocli.domain.character import load_character_from_disk
from hirocli.domain.model_catalog import clear_model_catalog_cache
from hirocli.domain.preferences import load_preferences, preferences_file
from hirocli.domain.preferences.convert_v4 import CHARACTER_V3_BACKUP, PREFERENCES_V3_BACKUP

V3_PREFS = {
    "version": 3,
    "llm": {
        "default_chat": "openai:gpt-6-luna",
        "default_tts": "google:gemini-3.1-flash-tts-preview",  # not a catalog speech model any more
        "default_tuning_profile": "balanced_chat",
        "default_stt": None,
    },
    "memory": {"retrieval": {"tuning_profile": "mine"}},
    "graph": {
        "extraction_model": "openai:gpt-6.1-sol",
        "small_tuning_profile": "graphiti_small",
        "eval": {"judge_model": "bogus:nope"},
    },
    "tuning_profiles": {
        "balanced_chat": {"label": "Balanced", "temperature": 0.4, "max_tokens": 999, "thinking": "low"},
        "mine": {"label": "Mine", "temperature": 0.1, "max_tokens": 3000, "thinking": "high", "num_ctx": 8192},
    },
}

V3_CHARACTER = {
    "id": "hiro",
    "name": "Hiro",
    "description": "",
    "llm_models": ["openai:gpt-6-luna", "unknown:x"],
    "tuning_profile": "mine",
    "voice_models": ["openai:gpt-4o-mini-tts"],
    "tts_instructions": "Warm",
    "tts_voice_by_provider": {"google": "Callirrhoe", "openai": "ash"},
    "emotions_enabled": False,
    "extras": {},
}


@pytest.fixture(autouse=True)
def _real_catalog(monkeypatch: pytest.MonkeyPatch):
    clear_model_catalog_cache()
    monkeypatch.delenv("IMAGE_VISION_MODEL", raising=False)
    yield
    clear_model_catalog_cache()


def _write_v3(ws: Path) -> Path:
    ws.mkdir(parents=True, exist_ok=True)
    preferences_file(ws).write_text(json.dumps(V3_PREFS), encoding="utf-8")
    char_dir = ws / "characters" / "hiro"
    char_dir.mkdir(parents=True)
    (char_dir / "character.json").write_text(json.dumps(V3_CHARACTER), encoding="utf-8")
    return char_dir


def test_v3_preferences_and_character_convert_to_profiles(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    char_dir = _write_v3(ws)

    prefs = load_preferences(ws)

    assert prefs.version == 4
    profiles = prefs.ai.profiles
    # Chat: the old model + the workspace's own balanced_chat tuning, as a "chat" preset profile.
    assert prefs.llm.chat_profile == "hiro-chat"
    chat = profiles["hiro-chat"]
    assert (chat.label, chat.model, chat.preset) == ("Hiro's chat", "openai:gpt-6-luna", "chat")
    assert (chat.temperature, chat.max_tokens, chat.thinking) == (0.4, 999, "low")
    # Memory: falls back to the chat model; its referenced tuning profile came from the raw file.
    memory = profiles[prefs.memory.retrieval.profile]
    assert (memory.model, memory.temperature, memory.max_tokens, memory.thinking, memory.num_ctx) == (
        "openai:gpt-6-luna", 0.1, 3000, "high", 8192
    )
    # Knowledge / rewrite: old chain → chat model, old code presets for tuning.
    knowledge = profiles[prefs.knowledge.answering.profile]
    assert (knowledge.model, knowledge.temperature, knowledge.max_tokens) == ("openai:gpt-6-luna", 0.2, 1600)
    rewrite = profiles[prefs.knowledge.answering.rewrite_profile]
    assert (rewrite.thinking, rewrite.max_tokens, rewrite.preset) == ("off", 1024, "rewrite")
    # Graph: extraction's own model; small borrows it (old chain) with its own preset.
    assert profiles[prefs.graph.extraction_profile].model == "openai:gpt-6.1-sol"
    small = profiles[prefs.graph.small_profile]
    assert (small.model, small.max_tokens, small.thinking) == ("openai:gpt-6.1-sol", 2048, "off")
    # Eval: an unknown model is skipped (field null), the others resolve along the old chain.
    assert prefs.graph.eval.judge_profile is None
    assert profiles[prefs.graph.eval.answer_profile].model == "openai:gpt-6-luna"
    assert profiles[prefs.graph.eval.retrieval_profile].model == "openai:gpt-6-luna"
    # Reading pictures: no IMAGE_VISION_MODEL, so it follows Hiro's chat model (with its own preset tuning).
    assert prefs.llm.vision_profile == "hiro-vision"
    assert profiles["hiro-vision"].model == chat.model and profiles["hiro-vision"].max_tokens == 4096

    # Hiro's voice: the old default_tts (replaced by google's recommended speech model) + the default
    # character's voice for google and its TTS instructions as the style.
    assert prefs.voice.hiro_profile == "hiro-voice"
    hiro_voice = prefs.voice.profiles["hiro-voice"]
    assert (hiro_voice.label, hiro_voice.model, hiro_voice.voice, hiro_voice.style) == (
        "Hiro's voice", "google:gemini-3.8-flash-tts", "callirrhoe", "Warm"
    )

    # The character: its model list → AI profiles (unknown model skipped), voice list → voice profiles.
    character = load_character_from_disk(ws, "hiro")
    assert character.ai_profiles == ["hiro-1"]
    assert character.voice_profiles == ["hiro-voice-1"]
    own = profiles["hiro-1"]
    assert (own.label, own.model, own.temperature, own.preset) == ("Hiro: openai:gpt-6-luna", "openai:gpt-6-luna", 0.1, None)
    own_voice = prefs.voice.profiles["hiro-voice-1"]
    assert (own_voice.model, own_voice.voice, own_voice.style) == ("openai:gpt-4o-mini-tts", "ash", "Warm")
    raw_char = json.loads((char_dir / "character.json").read_text(encoding="utf-8"))
    assert not {"llm_models", "tuning_profile", "voice_models", "tts_instructions", "tts_voice_by_provider"} & set(raw_char)

    # Backups, and the saved file is a clean v4.
    assert json.loads((ws / PREFERENCES_V3_BACKUP).read_text(encoding="utf-8")) == V3_PREFS
    assert json.loads((char_dir / CHARACTER_V3_BACKUP).read_text(encoding="utf-8")) == V3_CHARACTER
    saved = json.loads(preferences_file(ws).read_text(encoding="utf-8"))
    assert saved["version"] == 4
    assert "tuning_profiles" not in saved
    assert "default_chat" not in saved["llm"] and "default_tts" not in saved["llm"]


def test_conversion_is_idempotent(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    char_dir = _write_v3(ws)
    first = load_preferences(ws)
    saved = preferences_file(ws).read_text(encoding="utf-8")
    character = (char_dir / "character.json").read_text(encoding="utf-8")
    # A changed backup must not be overwritten by a later load either.
    (ws / PREFERENCES_V3_BACKUP).write_text("{}", encoding="utf-8")

    second = load_preferences(ws)

    assert second.model_dump() == first.model_dump()
    assert preferences_file(ws).read_text(encoding="utf-8") == saved
    assert (char_dir / "character.json").read_text(encoding="utf-8") == character
    assert (ws / PREFERENCES_V3_BACKUP).read_text(encoding="utf-8") == "{}"


def test_vision_from_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMAGE_VISION_MODEL", "openai:gpt-6-luna")
    ws = tmp_path / "ws"
    ws.mkdir()
    preferences_file(ws).write_text(json.dumps({"version": 3}), encoding="utf-8")

    prefs = load_preferences(ws)

    assert prefs.llm.vision_profile == "hiro-vision"
    vision = prefs.ai.profiles["hiro-vision"]
    assert (vision.model, vision.temperature, vision.max_tokens, vision.preset) == ("openai:gpt-6-luna", 0.7, 4096, "vision")
    # Nothing else had a model.
    assert prefs.llm.chat_profile is None and prefs.voice.hiro_profile is None


def test_unknown_models_never_fail_the_load(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    preferences_file(ws).write_text(
        json.dumps({"version": 3, "llm": {"default_chat": "nope:model", "default_tts": "acme:voice"}}), encoding="utf-8"
    )

    with caplog.at_level("WARNING"):
        prefs = load_preferences(ws)

    assert prefs.version == 4
    assert prefs.ai.profiles == {}
    assert prefs.llm.chat_profile is None
    assert prefs.voice.hiro_profile is None
    assert any("nope:model" in r.getMessage() for r in caplog.records)


def test_a_chat_model_the_catalog_dropped_becomes_its_providers_recommended_one(tmp_path: Path) -> None:
    """A models refresh pruned the old chat model: Hiro must keep talking, on the provider's recommended model."""
    from hirocli.domain.model_catalog import get_model_catalog

    ws = tmp_path / "ws"
    ws.mkdir()
    preferences_file(ws).write_text(
        json.dumps({"version": 3, "llm": {"default_chat": "google:gemini-3-flash-preview"}}), encoding="utf-8"
    )

    prefs = load_preferences(ws)

    recommended = get_model_catalog().suggested_defaults("google").get("chat")
    assert recommended and prefs.llm.chat_profile == "hiro-chat"
    assert prefs.ai.profiles["hiro-chat"].model == recommended
