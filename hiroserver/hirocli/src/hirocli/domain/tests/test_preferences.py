"""Tests for preferences resolution (canonical ids + availability)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.model_catalog import ModelCatalog, clear_model_catalog_cache
from hirocli.domain.preferences import (
    DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID,
    LLMPreferences,
    MediaPreferences,
    MemoryPreferences,
    ModalityFlags,
    PREFERENCE_SECTIONS,
    PROMPT_DEFAULTS,
    TuningProfile,
    WorkspacePreferences,
    knowledge_answering_model_source,
    load_preferences,
    preferences_file,
    resolve_knowledge_answering_llm,
    resolve_llm,
    save_preferences,
)
from hirocli.domain.server_info import (
    build_channel_list_entries,
    build_policy_snapshot,
)


@pytest.fixture(autouse=True)
def _clear_cat() -> None:
    clear_model_catalog_cache()
    yield
    clear_model_catalog_cache()


def _fixture_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Minimal registry pointing tmp_path as workspace."""
    from hirocli.domain import workspace as ws_mod

    wid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    reg = ws_mod.WorkspaceRegistry(
        default_workspace=wid,
        workspaces={
            wid: ws_mod.WorkspaceEntry(
                id=wid,
                name="t",
                path=str(tmp_path.resolve()),
                port_slot=0,
            ),
        },
    )
    monkeypatch.setattr(ws_mod, "load_registry", lambda: reg)
    return wid


def _patch_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hirocli.domain import model_catalog as mc

    doc = {
        "catalog_version": "1.0.0",
        "providers": [
            {
                "id": "openai",
                "display_name": "OpenAI",
                "hosting": "cloud",
                "credential_env_keys": ["OPENAI_API_KEY"],
                "metadata_updated_at": "2026-01-01",
            },
        ],
        "models": [
            {
                "id": "openai:gpt-test",
                "provider_id": "openai",
                "display_name": "G",
                "model_kind": "chat",
            },
            {
                "id": "openai:gpt-other",
                "provider_id": "openai",
                "display_name": "G2",
                "model_kind": "chat",
            },
        ],
    }
    p = tmp_path / "cat.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    cat = ModelCatalog.load_from_path(p)
    monkeypatch.setattr(mc, "get_model_catalog", lambda: cat)
    monkeypatch.setattr("hirocli.domain.credential_store.get_model_catalog", lambda: cat)


def test_resolve_llm_none_without_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    prefs = WorkspacePreferences()
    assert resolve_llm(prefs, tmp_path, "chat") is None


def test_workspace_preferences_media_defaults() -> None:
    prefs = WorkspacePreferences()
    assert prefs.media.input.voice is True
    assert prefs.media.output.voice is False
    assert prefs.media.input.image is False
    assert prefs.media.output.file is False
    assert prefs.memory.enabled is False
    assert prefs.chat.max_messages == 6
    assert prefs.llm.default_tuning_profile == "balanced_chat"
    assert prefs.memory.default_tuning_profile == "memory_extraction"
    assert prefs.knowledge.default_tuning_profile == DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID
    assert prefs.tuning_profiles["balanced_chat"].locked is True
    assert prefs.tuning_profiles["memory_extraction"].locked is True
    assert prefs.tuning_profiles[DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID].locked is True


def test_memory_preferences_enabled_independent_of_legacy_models() -> None:
    # Memory now rides the shared Graphiti engine, so enabling it no longer requires the
    # mem0-legacy model fields (Phase 3 removed the auto-disable validator). Engine
    # availability is enforced later by create_memory_service, not by this model.
    prefs = WorkspacePreferences(
        memory=MemoryPreferences(enabled=True, default_embedding_model=None)
    )
    assert prefs.memory.enabled is True


def test_preference_sections_are_first_level_only() -> None:
    assert [section.key for section in PREFERENCE_SECTIONS] == [
        "llm",
        "media",
        "memory",
        "knowledge",
        "graph",
        "chat",
    ]


def test_prompt_defaults_match_model_defaults() -> None:
    # PROMPT_DEFAULTS feeds the admin UI's "Restore default" affordance for prompt editors;
    # each dotted path must resolve on a default WorkspacePreferences to the exact same text,
    # otherwise restore would write a stale copy of the default instead of the real one.
    prefs = WorkspacePreferences()
    for path, default_text in PROMPT_DEFAULTS.items():
        node: object = prefs
        for part in path.split("."):
            node = getattr(node, part)
        assert node == default_text, f"PROMPT_DEFAULTS out of sync for {path}"
        assert isinstance(default_text, str) and default_text.strip()


def test_load_preferences_missing_file_persists_defaults(tmp_path: Path) -> None:
    ws = tmp_path / "fresh_ws"
    assert not preferences_file(ws).exists()
    prefs = load_preferences(ws)
    assert preferences_file(ws).is_file()
    assert prefs.version == 3
    assert prefs.media.input.voice is True
    assert prefs.chat.max_messages == 6


def test_resolve_llm_with_default_and_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    secrets: dict[tuple[str, str], str] = {}
    CredentialStore(tmp_path, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", _test_secrets=secrets).set_api_key(
        "openai", "sk"
    )
    prefs = WorkspacePreferences(
        llm=LLMPreferences(
            default_chat="openai:gpt-test",
        ),
        tuning_profiles={
            "balanced_chat": TuningProfile(
                label="Balanced chat",
                locked=True,
                temperature=0.5,
                max_tokens=512,
                thinking="low",
            ),
        },
    )
    r = resolve_llm(prefs, tmp_path, "chat")
    assert r is not None
    assert r.model_id == "openai:gpt-test"
    assert r.temperature == 0.5
    assert r.max_tokens == 512
    assert r.thinking == "low"


def test_resolve_knowledge_answering_llm_inherits_default_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    wid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    CredentialStore(tmp_path, wid, _test_secrets={}).set_api_key("openai", "sk")
    prefs = WorkspacePreferences(
        llm=LLMPreferences(default_chat="openai:gpt-test"),
        tuning_profiles={
            DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID: TuningProfile(
                label="Knowledge answering",
                locked=True,
                temperature=0.15,
                max_tokens=1200,
                thinking=None,
            ),
        },
    )

    r = resolve_knowledge_answering_llm(prefs, tmp_path)

    assert r is not None
    assert r.model_id == "openai:gpt-test"
    assert r.temperature == 0.15
    assert r.max_tokens == 1200
    assert knowledge_answering_model_source(prefs) == "llm.default_chat"


def test_resolve_knowledge_answering_llm_explicit_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    wid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    CredentialStore(tmp_path, wid, _test_secrets={}).set_api_key("openai", "sk")
    prefs = WorkspacePreferences(
        llm=LLMPreferences(default_chat="openai:gpt-test"),
    )
    prefs.knowledge.answering.model = "openai:gpt-other"

    r = resolve_knowledge_answering_llm(prefs, tmp_path)

    assert r is not None
    assert r.model_id == "openai:gpt-other"
    assert knowledge_answering_model_source(prefs) == "knowledge.answering.model"


def test_resolve_knowledge_answering_llm_none_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    prefs = WorkspacePreferences(
        llm=LLMPreferences(default_chat="openai:gpt-test"),
    )

    assert resolve_knowledge_answering_llm(prefs, tmp_path) is None


def test_resolve_character_llm_prefers_character_list_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    wid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    CredentialStore(tmp_path, wid, _test_secrets={}).set_api_key("openai", "sk")
    prefs = WorkspacePreferences(
        llm=LLMPreferences(
            default_chat="openai:gpt-test",
        ),
        tuning_profiles={
            "balanced_chat": TuningProfile(
                label="Balanced chat",
                locked=True,
                temperature=0.2,
                max_tokens=99,
            ),
        },
    )
    from hirocli.domain.preferences import resolve_character_llm

    r = resolve_character_llm(
        ["openai:gpt-other", "openai:gpt-test"],
        prefs,
        tmp_path,
    )
    assert r is not None
    assert r.model_id == "openai:gpt-other"
    assert r.temperature == 0.2
    assert r.max_tokens == 99


def test_resolve_character_llm_uses_character_tuning_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    wid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    CredentialStore(tmp_path, wid, _test_secrets={}).set_api_key("openai", "sk")
    prefs = WorkspacePreferences(
        llm=LLMPreferences(default_chat="openai:gpt-test"),
        tuning_profiles={
            "balanced_chat": TuningProfile(label="Balanced chat", locked=True, max_tokens=512),
            "deep": TuningProfile(
                label="Deep",
                locked=False,
                temperature=0.2,
                max_tokens=4096,
                thinking="medium",
            ),
        },
    )
    from hirocli.domain.preferences import resolve_character_llm

    r = resolve_character_llm([], prefs, tmp_path, tuning_profile="deep")

    assert r is not None
    assert r.model_id == "openai:gpt-test"
    assert r.temperature == 0.2
    assert r.max_tokens == 4096
    assert r.thinking == "medium"


def test_resolve_character_llm_falls_back_when_list_unusable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    wid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    CredentialStore(tmp_path, wid, _test_secrets={}).set_api_key("openai", "sk")
    prefs = WorkspacePreferences(
        llm=LLMPreferences(
            default_chat="openai:gpt-test",
        ),
    )
    from hirocli.domain.preferences import resolve_character_llm

    r = resolve_character_llm(["openai:unknown", "bad"], prefs, tmp_path)
    assert r is not None
    assert r.model_id == "openai:gpt-test"


def test_resolve_character_voice_applies_character_tts_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Character-level voice preset / instructions attach to the resolved TTS provider."""
    _fixture_workspace(tmp_path, monkeypatch)
    from hirocli.domain import model_catalog as mc

    doc = {
        "catalog_version": "1.0.0",
        "providers": [
            {
                "id": "openai",
                "display_name": "OpenAI",
                "hosting": "cloud",
                "credential_env_keys": ["OPENAI_API_KEY"],
                "metadata_updated_at": "2026-01-01",
            },
        ],
        "models": [
            {
                "id": "openai:tts-one",
                "provider_id": "openai",
                "display_name": "TTS One",
                "model_kind": "tts",
            },
        ],
    }
    p = tmp_path / "cat.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    cat = ModelCatalog.load_from_path(p)
    monkeypatch.setattr(mc, "get_model_catalog", lambda: cat)
    monkeypatch.setattr("hirocli.domain.credential_store.get_model_catalog", lambda: cat)

    wid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    CredentialStore(tmp_path, wid, _test_secrets={}).set_api_key("openai", "sk")
    prefs = WorkspacePreferences(llm=LLMPreferences(default_tts="openai:tts-one"))
    from hirocli.domain.preferences import resolve_character_voice

    r = resolve_character_voice(
        [],
        prefs,
        tmp_path,
        tts_instructions=" Speak calmly. ",
        tts_voice_by_provider={"openai": "orchid"},
    )
    assert r is not None
    assert r.model == "tts-one"
    assert r.voice == "orchid"
    assert r.instructions == "Speak calmly."

    r2 = resolve_character_voice(
        ["openai:tts-one"],
        prefs,
        tmp_path,
        tts_instructions="Hi.",
        tts_voice_by_provider={"openai": "ash"},
    )
    assert r2 is not None and r2.model == "tts-one" and r2.voice == "ash" and r2.instructions == "Hi."


def test_build_policy_snapshot_and_channel_list_voice_capabilities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture_workspace(tmp_path, monkeypatch)
    from hirocli.domain import model_catalog as mc
    from hirocli.domain.character import create_character
    from hirocli.domain.conversation_channel import create_channel

    doc = {
        "catalog_version": "1.0.0",
        "providers": [
            {
                "id": "openai",
                "display_name": "OpenAI",
                "hosting": "cloud",
                "credential_env_keys": ["OPENAI_API_KEY"],
                "metadata_updated_at": "2026-01-01",
            },
        ],
        "models": [
            {
                "id": "openai:gpt-test",
                "provider_id": "openai",
                "display_name": "G",
                "model_kind": "chat",
            },
            {
                "id": "openai:stt-one",
                "provider_id": "openai",
                "display_name": "STT",
                "model_kind": "stt",
            },
            {
                "id": "openai:tts-one",
                "provider_id": "openai",
                "display_name": "TTS",
                "model_kind": "tts",
            },
        ],
    }
    p = tmp_path / "cat.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    cat = ModelCatalog.load_from_path(p)
    monkeypatch.setattr(mc, "get_model_catalog", lambda: cat)
    monkeypatch.setattr("hirocli.domain.credential_store.get_model_catalog", lambda: cat)

    wid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    CredentialStore(tmp_path, wid, _test_secrets={}).set_api_key("openai", "sk")

    save_preferences(
        tmp_path,
        WorkspacePreferences(
            llm=LLMPreferences(
                default_chat="openai:gpt-test",
                default_stt="openai:stt-one",
                default_tts="openai:tts-one",
            ),
            media=MediaPreferences(
                input=ModalityFlags(voice=True),
                output=ModalityFlags(voice=True),
            ),
        ),
    )
    create_character(
        tmp_path,
        "voice-bot",
        "Voice Bot",
        voice_models=["openai:tts-one"],
    )
    create_channel(
        tmp_path,
        name="Voice Bot",
        character_id="voice-bot",
        user_id=1,
    )

    policy_snap = build_policy_snapshot(tmp_path)
    assert policy_snap.policy.input.voice is True
    assert policy_snap.policy.output.voice is True

    channel_list = build_channel_list_entries(tmp_path)
    voice_entry = next(channel for channel in channel_list if channel.character.id == "voice-bot")
    assert voice_entry.name == "Voice Bot"
    assert voice_entry.character_id == "voice-bot"
    assert voice_entry.capabilities.input.voice is True
    assert voice_entry.capabilities.output.voice is True
