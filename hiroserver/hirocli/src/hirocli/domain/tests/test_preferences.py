"""Tests for preferences resolution (canonical ids + availability)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.model_catalog import ModelCatalog, clear_model_catalog_cache
from hirocli.domain.preferences import (
    DEFAULT_ANSWER_PROMPT_ID,
    DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID,
    DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID,
    DEFAULT_MEMORY_CHAT_RETRIEVAL_AGENT_PROMPT,
    DEFAULT_MEMORY_EVAL_ANSWER_PROMPT,
    DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT,
    DEFAULT_RETRIEVAL_AGENT_PROMPT_ID,
    AnswerPromptProfile,
    LLMPreferences,
    MediaPreferences,
    MemoryPreferences,
    ModalityFlags,
    PREFERENCE_SECTIONS,
    PROMPT_DEFAULTS,
    RetrievalAgentLimits,
    TuningProfile,
    WorkspacePreferences,
    knowledge_answering_model_source,
    load_preferences,
    preferences_file,
    resolve_chat_retrieval_agent_prompt,
    resolve_knowledge_answering_llm,
    resolve_llm,
    resolve_retrieval_agent_prompt,
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


def test_save_preferences_prunes_default_prompts(tmp_path: Path) -> None:
    # A prompt left at its built-in default must NOT be persisted: the key stays absent so the code
    # constant re-applies on load (a true reset that tracks future default edits). See Option E.
    import json as _json

    ws = tmp_path / "ws"
    save_preferences(ws, WorkspacePreferences())
    raw = _json.loads(preferences_file(ws).read_text(encoding="utf-8"))
    assert "prompt" not in raw["knowledge"]["answering"]
    assert "judge_prompt" not in raw["graph"]["eval"]
    # The mem-eval answer prompt is now a named library (dict), always materialized like
    # tuning_profiles — so it stays present, and its locked default profile reloads with the
    # built-in default text via resolve_answer_prompt.
    reloaded = load_preferences(ws)
    _, default_text = reloaded.graph.eval.resolve_answer_prompt(None)
    assert default_text == DEFAULT_MEMORY_EVAL_ANSWER_PROMPT


def test_answer_prompt_library_roundtrips(tmp_path: Path) -> None:
    # The answer-prompt library persists in full (a dict, like tuning_profiles); an added profile
    # round-trips and resolve_answer_prompt returns its text by id, with an unknown id falling
    # back to the locked default profile's text.
    import json as _json

    ws = tmp_path / "ws"
    prefs = WorkspacePreferences()
    prefs.graph.eval.answer_prompts["strict"] = AnswerPromptProfile(
        label="Strict", prompt="Answer only from context."
    )
    save_preferences(ws, prefs)
    raw = _json.loads(preferences_file(ws).read_text(encoding="utf-8"))
    assert raw["graph"]["eval"]["answer_prompts"]["strict"]["prompt"] == "Answer only from context."
    reloaded = load_preferences(ws)
    assert reloaded.graph.eval.resolve_answer_prompt("strict") == (
        "Strict",
        "Answer only from context.",
    )
    _, default_text = reloaded.graph.eval.resolve_answer_prompt("nope")
    assert default_text == DEFAULT_MEMORY_EVAL_ANSWER_PROMPT


def test_resolve_active_answer_prompt_uses_active_id() -> None:
    # The answer step now reads the persisted active_answer_prompt_id (mirrors the retrieval agent),
    # returning (id, label, text). A blank profile body falls back to the built-in default text.
    prefs = WorkspacePreferences()
    prefs.graph.eval.answer_prompts["variant"] = AnswerPromptProfile(
        label="Variant", prompt="Answer tersely."
    )
    prefs.graph.eval.active_answer_prompt_id = "variant"
    pid, label, text = prefs.graph.eval.resolve_active_answer_prompt()
    assert (pid, label, text) == ("variant", "Variant", "Answer tersely.")

    prefs.graph.eval.answer_prompts["blank"] = AnswerPromptProfile(label="Blank", prompt="")
    prefs.graph.eval.active_answer_prompt_id = "blank"
    pid, _label, text = prefs.graph.eval.resolve_active_answer_prompt()
    assert pid == "blank"
    assert text == DEFAULT_MEMORY_EVAL_ANSWER_PROMPT


def test_resolve_active_answer_prompt_defaults_to_locked_default() -> None:
    pid, _label, text = WorkspacePreferences().graph.eval.resolve_active_answer_prompt()
    assert pid == DEFAULT_ANSWER_PROMPT_ID
    assert text == DEFAULT_MEMORY_EVAL_ANSWER_PROMPT


def test_retrieval_agent_defaults() -> None:
    limits = WorkspacePreferences().graph.eval.retrieval_agent
    assert limits.max_agent_turns == 4
    assert limits.max_parallel_searches == 3
    assert limits.limit_default == 20
    assert limits.limit_min == 10
    assert limits.limit_max == 40
    assert limits.hops_max == 3


def test_retrieval_agent_limit_coherence_validator() -> None:
    with pytest.raises(ValueError, match="limit_min"):
        RetrievalAgentLimits(limit_min=30, limit_default=20)


def test_retrieval_agent_caps_clamped_to_pydantic_bounds() -> None:
    with pytest.raises(Exception):
        RetrievalAgentLimits(max_parallel_searches=99)


def test_resolve_retrieval_agent_prompt_blank_falls_back_to_default() -> None:
    prefs = WorkspacePreferences()
    prefs.graph.eval.retrieval_agent_prompts["custom"] = AnswerPromptProfile(
        label="Custom", prompt=""
    )
    prefs.graph.eval.active_retrieval_agent_prompt_id = "custom"
    pid, text = resolve_retrieval_agent_prompt(prefs)
    assert pid == "custom"
    assert text == DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT


def test_resolve_retrieval_agent_prompt_uses_active_id() -> None:
    prefs = WorkspacePreferences()
    prefs.graph.eval.retrieval_agent_prompts["variant"] = AnswerPromptProfile(
        label="Variant", prompt="Search carefully."
    )
    prefs.graph.eval.active_retrieval_agent_prompt_id = "variant"
    pid, text = resolve_retrieval_agent_prompt(prefs)
    assert pid == "variant"
    assert text == "Search carefully."


def test_retrieval_agent_prompt_default_in_builtin_defaults() -> None:
    default_profile = WorkspacePreferences().graph.eval.retrieval_agent_prompts[
        DEFAULT_RETRIEVAL_AGENT_PROMPT_ID
    ]
    assert default_profile.prompt == DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT
    pid, text = resolve_retrieval_agent_prompt(WorkspacePreferences())
    assert pid == DEFAULT_RETRIEVAL_AGENT_PROMPT_ID
    assert text == DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT


def test_chat_retrieval_agent_prompt_is_locked_default_and_resolves() -> None:
    """Phase 1: the SHARED library hosts a locked ``chat`` profile; the chat resolver selects it via
    ``memory.retrieval.active_prompt_id`` (chat's own pointer), independent of the eval active id."""
    chat_profile = WorkspacePreferences().graph.eval.retrieval_agent_prompts[
        DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID
    ]
    assert chat_profile.locked is True
    assert chat_profile.prompt == DEFAULT_MEMORY_CHAT_RETRIEVAL_AGENT_PROMPT

    # Default memory pointer → the chat profile.
    pid, text = resolve_chat_retrieval_agent_prompt(WorkspacePreferences())
    assert pid == DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID
    assert text == DEFAULT_MEMORY_CHAT_RETRIEVAL_AGENT_PROMPT

    # The two surfaces read INDEPENDENT pointers against the one shared library: pointing chat at the
    # eval default resolves eval text, while eval's own pointer is untouched.
    prefs = WorkspacePreferences()
    prefs.memory.retrieval.active_prompt_id = DEFAULT_RETRIEVAL_AGENT_PROMPT_ID
    assert resolve_chat_retrieval_agent_prompt(prefs) == (
        DEFAULT_RETRIEVAL_AGENT_PROMPT_ID,
        DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT,
    )
    # Eval active id does NOT affect chat.
    prefs.graph.eval.active_retrieval_agent_prompt_id = DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID
    assert resolve_chat_retrieval_agent_prompt(prefs)[0] == DEFAULT_RETRIEVAL_AGENT_PROMPT_ID
    assert resolve_retrieval_agent_prompt(prefs)[0] == DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID


def test_memory_retrieval_defaults_parity_with_eval_caps() -> None:
    """The chat retrieval caps default to eval parity (max_agent_turns=4), NOT a tight turns=1."""
    retrieval = WorkspacePreferences().memory.retrieval
    assert retrieval.limits.max_agent_turns == 4
    assert retrieval.active_prompt_id == DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID
    assert retrieval.model is None


def test_locked_default_prompts_reseed_from_code_on_load(tmp_path: Path) -> None:
    """Stale-locked-default fix: a workspace whose persisted LOCKED ``default`` profile holds OLD
    text (a code-default edit landed after the workspace was created) gets that text overwritten
    from the code constant on load, while a user's CUSTOM (non-locked) profile is preserved."""
    import json as _json

    ws = tmp_path / "ws"
    save_preferences(ws, WorkspacePreferences())
    raw = _json.loads(preferences_file(ws).read_text(encoding="utf-8"))
    # Simulate an older workspace: stale text baked into the locked defaults + a user custom profile.
    raw.setdefault("graph", {}).setdefault("eval", {})
    raw["graph"]["eval"]["retrieval_agent_prompts"] = {
        "default": {"label": "Default", "locked": True, "prompt": "OLD STALE RETRIEVAL PROMPT"},
        "mine": {"label": "Mine", "locked": False, "prompt": "my custom retrieval prompt"},
    }
    raw["graph"]["eval"]["answer_prompts"] = {
        "default": {"label": "Default (grounded)", "locked": True, "prompt": "OLD STALE ANSWER PROMPT"},
    }
    preferences_file(ws).write_text(_json.dumps(raw), encoding="utf-8")

    reloaded = load_preferences(ws)
    # Locked defaults are re-seeded from the live code constants…
    assert (
        reloaded.graph.eval.retrieval_agent_prompts["default"].prompt
        == DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT
    )
    assert (
        reloaded.graph.eval.answer_prompts["default"].prompt == DEFAULT_MEMORY_EVAL_ANSWER_PROMPT
    )
    # …while the user's custom (non-locked) profile is left untouched.
    assert reloaded.graph.eval.retrieval_agent_prompts["mine"].prompt == "my custom retrieval prompt"


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
