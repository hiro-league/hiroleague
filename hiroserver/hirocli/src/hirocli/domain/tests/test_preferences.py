"""Tests for preferences resolution (canonical ids + availability)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.model_catalog import ModelCatalog, clear_model_catalog_cache
from hirocli.domain.preferences import (
    DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID,
    DEFAULT_MEMORY_CHAT_RETRIEVAL_AGENT_PROMPT,
    AiProfile,
    MediaPreferences,
    MemoryPreferences,
    ModalityFlags,
    PREFERENCE_SECTIONS,
    PROMPT_DEFAULTS,
    PromptProfile,
    WorkspacePreferences,
    job_model_source,
    load_preferences,
    preferences_file,
    resolve_chat_retrieval_agent_prompt,
    resolve_job_model,
    resolve_knowledge_answering_llm,
    resolved_from_profile,
    save_preferences,
)
from hiro_memory.settings import RetrievalAgentLimits
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
            # Phase 7b step 5: a provider without a key and a local server, for the fallback chain.
            {
                "id": "deepseek",
                "display_name": "DeepSeek",
                "hosting": "cloud",
                "credential_env_keys": ["DEEPSEEK_API_KEY"],
                "metadata_updated_at": "2026-01-01",
            },
            {
                "id": "ollama",
                "display_name": "Ollama",
                "hosting": "local",
                "credential_env_keys": [],
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
            {
                "id": "deepseek:ds-test",
                "provider_id": "deepseek",
                "display_name": "DS",
                "model_kind": "chat",
            },
        ],
    }
    p = tmp_path / "cat.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    cat = ModelCatalog.load_from_path(p)
    monkeypatch.setattr(mc, "get_model_catalog", lambda: cat)
    monkeypatch.setattr("hirocli.domain.credential_store.get_model_catalog", lambda: cat)


def test_resolve_job_model_none_without_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    prefs = WorkspacePreferences()
    assert resolve_job_model(prefs, tmp_path, "chat") is None


def test_workspace_preferences_media_defaults() -> None:
    prefs = WorkspacePreferences()
    assert prefs.media.input.voice is True
    assert prefs.media.output.voice is True
    assert prefs.media.input.image is False
    assert prefs.media.output.file is False
    assert prefs.memory.enabled is True
    assert prefs.chat.max_messages == 6
    # Phase 7b step 5: no tuning profiles; every job's AI profile starts unset.
    assert prefs.llm.chat_profile is None
    assert prefs.voice.hiro_profile is None
    assert prefs.ai.profiles == {}


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
    assert prefs.version == 5
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
    # The retrieval-agent prompt library is a dict, always materialized like image_profiles: its
    # locked chat profile reloads with the built-in text.
    reloaded = load_preferences(ws)
    assert resolve_chat_retrieval_agent_prompt(reloaded) == (
        DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID,
        DEFAULT_MEMORY_CHAT_RETRIEVAL_AGENT_PROMPT,
    )


def test_retrieval_agent_limit_coherence_validator() -> None:
    with pytest.raises(ValueError, match="limit_min"):
        RetrievalAgentLimits(limit_min=30, limit_default=20)


def test_retrieval_agent_caps_clamped_to_pydantic_bounds() -> None:
    with pytest.raises(Exception):
        RetrievalAgentLimits(max_parallel_searches=99)


def test_chat_retrieval_prompt_library_roundtrips_and_resolves(tmp_path: Path) -> None:
    # An added profile persists in full and resolves by the active id; blank text falls back to the
    # built-in prompt; an unknown id falls back to the locked chat profile.
    import json as _json

    ws = tmp_path / "ws"
    prefs = WorkspacePreferences()
    prefs.memory.retrieval.prompts["variant"] = PromptProfile(label="Variant", prompt="Search carefully.")
    prefs.memory.retrieval.active_prompt_id = "variant"
    save_preferences(ws, prefs)
    raw = _json.loads(preferences_file(ws).read_text(encoding="utf-8"))
    assert raw["memory"]["retrieval"]["prompts"]["variant"]["prompt"] == "Search carefully."
    reloaded = load_preferences(ws)
    assert resolve_chat_retrieval_agent_prompt(reloaded) == ("variant", "Search carefully.")

    reloaded.memory.retrieval.prompts["blank"] = PromptProfile(label="Blank", prompt="")
    reloaded.memory.retrieval.active_prompt_id = "blank"
    assert resolve_chat_retrieval_agent_prompt(reloaded) == ("blank", DEFAULT_MEMORY_CHAT_RETRIEVAL_AGENT_PROMPT)

    reloaded.memory.retrieval.active_prompt_id = "gone"
    assert resolve_chat_retrieval_agent_prompt(reloaded) == (
        DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID,
        DEFAULT_MEMORY_CHAT_RETRIEVAL_AGENT_PROMPT,
    )


def test_chat_retrieval_agent_prompt_is_locked_default() -> None:
    chat_profile = WorkspacePreferences().memory.retrieval.prompts[DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID]
    assert chat_profile.locked is True
    assert chat_profile.prompt == DEFAULT_MEMORY_CHAT_RETRIEVAL_AGENT_PROMPT


def test_memory_retrieval_defaults() -> None:
    """The chat retrieval caps default lean (max_agent_turns=3, num-results 5/10/25)."""
    retrieval = WorkspacePreferences().memory.retrieval
    assert retrieval.limits.max_agent_turns == 3
    assert retrieval.limits.limit_default == 10
    assert retrieval.limits.limit_min == 5
    assert retrieval.limits.limit_max == 25
    assert retrieval.active_prompt_id == DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID
    assert retrieval.profile is None


def test_locked_default_prompts_reseed_from_code_on_load(tmp_path: Path) -> None:
    """A workspace whose persisted LOCKED ``chat`` profile holds old text gets it overwritten from the
    code constant on load, while the owner's own (non-locked) profile is kept."""
    import json as _json

    ws = tmp_path / "ws"
    save_preferences(ws, WorkspacePreferences())
    raw = _json.loads(preferences_file(ws).read_text(encoding="utf-8"))
    raw["memory"]["retrieval"]["prompts"] = {
        "chat": {"label": "Chat", "locked": True, "prompt": "OLD STALE RETRIEVAL PROMPT"},
        "mine": {"label": "Mine", "locked": False, "prompt": "my custom retrieval prompt"},
    }
    preferences_file(ws).write_text(_json.dumps(raw), encoding="utf-8")

    reloaded = load_preferences(ws)
    assert reloaded.memory.retrieval.prompts["chat"].prompt == DEFAULT_MEMORY_CHAT_RETRIEVAL_AGENT_PROMPT
    assert reloaded.memory.retrieval.prompts["mine"].prompt == "my custom retrieval prompt"


def _file_with_eval_settings(ws: Path) -> None:
    """A v5 preferences.json as the live core and env0 hold it: ``graph.eval`` (eval's own settings and
    the retrieval-prompt library chat picks from), AI profiles made for the eval jobs
    (``preset: eval_answer``…), and EvalHiro's uses pointing at them."""
    import json as _json

    save_preferences(ws, WorkspacePreferences())
    raw = _json.loads(preferences_file(ws).read_text(encoding="utf-8"))
    raw["memory"]["retrieval"].pop("prompts", None)
    raw["memory"]["retrieval"]["active_prompt_id"] = "mine"
    raw["graph"]["eval"] = {
        "answer_prompts": {"default": {"label": "Default (grounded)", "locked": True, "prompt": "answer"}},
        "active_answer_prompt_id": "default",
        "judge_prompt": "judge",
        "answer_profile": "hiro-eval-answer",
        "judge_profile": "hiro-eval-judge",
        "retrieval_profile": "hiro-eval-retrieval",
        "show_event_time": True,
        "max_elements_per_kind": 30,
        "retrieval_agent": {"max_agent_turns": 4, "limit_default": 20, "limit_min": 10, "limit_max": 40},
        "retrieval_agent_prompts": {
            "default": {"label": "Default (eval)", "locked": True, "prompt": "eval retrieval"},
            "chat": {"label": "Chat", "locked": True, "prompt": "old chat text"},
            "mine": {"label": "Mine", "locked": False, "prompt": "my chat retrieval prompt"},
        },
        "active_retrieval_agent_prompt_id": "default",
    }
    for job in ("eval_answer", "eval_judge", "eval_retrieval"):
        pid = "hiro-" + job.replace("_", "-")
        raw["ai"]["profiles"][pid] = {"label": job, "model": "claude_code:sonnet", "preset": job}
        raw["ai"]["uses"]["eval:" + job.split("_")[1]] = pid
    preferences_file(ws).write_text(_json.dumps(raw), encoding="utf-8")


def test_a_file_with_eval_settings_still_loads_and_keeps_chat_prompts(tmp_path: Path) -> None:
    """Family data: a preferences.json holding the eval settings loads. ``graph.eval`` is ignored, the
    owner's chat retrieval prompts move to ``memory.retrieval.prompts`` (the active one still resolves),
    and the eval jobs' profiles stay as the owner's own (no preset), with EvalHiro's uses intact."""
    ws = tmp_path / "ws"
    _file_with_eval_settings(ws)

    prefs = load_preferences(ws)
    assert "eval" not in prefs.graph.model_dump()
    assert sorted(prefs.memory.retrieval.prompts) == ["chat", "mine"]
    assert prefs.memory.retrieval.prompts["chat"].prompt == DEFAULT_MEMORY_CHAT_RETRIEVAL_AGENT_PROMPT
    assert resolve_chat_retrieval_agent_prompt(prefs) == ("mine", "my chat retrieval prompt")
    for pid in ("hiro-eval-answer", "hiro-eval-judge", "hiro-eval-retrieval"):
        assert prefs.ai.profiles[pid].preset is None
    assert prefs.ai.uses["eval:answer"] == "hiro-eval-answer"

    # Saved once, the file carries the prompts in their place and no eval section.
    save_preferences(ws, prefs)
    again = load_preferences(ws)
    assert resolve_chat_retrieval_agent_prompt(again) == ("mine", "my chat retrieval prompt")
    raw = preferences_file(ws).read_text(encoding="utf-8")
    assert '"eval":' not in raw and "my chat retrieval prompt" in raw


WID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _with_profiles(profiles: dict[str, dict], **fields: str | None) -> WorkspacePreferences:
    """Preferences holding ``profiles`` (AI profile fields) and job fields given as dotted paths
    with ``__`` for dots (``llm__chat_profile="p"``)."""
    data: dict = {"ai": {"profiles": profiles}}
    for key, value in fields.items():
        node = data
        parts = key.split("__")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return WorkspacePreferences.model_validate(data)


def _key(tmp_path: Path, provider: str = "openai") -> None:
    CredentialStore(tmp_path, WID, _test_secrets={}).set_api_key(provider, "sk")


def test_resolve_job_model_maps_profile_tuning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Phase 7b step 5: a job's model + tuning come from its ONE AI profile.
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    _key(tmp_path)
    prefs = _with_profiles(
        {"chat": {"label": "Chat", "model": "openai:gpt-test", "temperature": 0.5, "max_tokens": 512,
                  "thinking": "low", "num_ctx": 4096, "instructions": "Be brief."}},
        llm__chat_profile="chat",
    )
    r = resolve_job_model(prefs, tmp_path, "chat")
    assert r is not None
    assert (r.model_id, r.temperature, r.max_tokens, r.thinking) == ("openai:gpt-test", 0.5, 512, "low")
    assert r.num_ctx is None  # context window only for local models
    assert (r.profile_id, r.profile_name, r.instructions) == ("chat", "Chat", "Be brief.")


def test_resolve_job_model_profile_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Unset tuning means what ai_ask's ChatModelProvider uses: 0.7 / 8192.
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    _key(tmp_path)
    prefs = _with_profiles({"p": {"label": "P", "model": "openai:gpt-test"}}, llm__chat_profile="p")
    r = resolve_job_model(prefs, tmp_path, "chat")
    assert r is not None and (r.temperature, r.max_tokens, r.thinking) == (0.7, 8192, None)


def test_resolved_from_profile_keeps_num_ctx_for_local_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_catalog(tmp_path, monkeypatch)
    local = resolved_from_profile("l", AiProfile(label="L", model="ollama:gemma", num_ctx=4096))
    assert local.num_ctx == 4096
    cloud = resolved_from_profile("c", AiProfile(label="C", model="openai:gpt-test", num_ctx=4096))
    assert cloud.num_ctx is None


def test_resolve_job_model_walks_the_fallback_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # First profile in the chain whose model is available; a plan-tool model is skipped (not a
    # LangChain model), as is a provider without a key.
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    _key(tmp_path)
    prefs = _with_profiles(
        {
            "a": {"label": "A", "model": "deepseek:ds-test", "fallback": "b"},
            "b": {"label": "B", "model": "claude_code:sonnet", "fallback": "c"},
            "c": {"label": "C", "model": "openai:gpt-other", "max_tokens": 77},
        },
        llm__chat_profile="a",
    )
    r = resolve_job_model(prefs, tmp_path, "chat")
    assert r is not None
    assert (r.model_id, r.profile_id, r.max_tokens) == ("openai:gpt-other", "c", 77)


def test_resolve_job_model_set_but_unavailable_stays_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A set field whose chain has nothing available does NOT borrow another job's model.
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    _key(tmp_path)
    prefs = _with_profiles(
        {"chat": {"label": "Chat", "model": "openai:gpt-test"}, "ds": {"label": "DS", "model": "deepseek:ds-test"}},
        llm__chat_profile="chat",
        knowledge__answering__profile="ds",
    )
    assert resolve_job_model(prefs, tmp_path, "knowledge") is None


def test_resolve_job_model_null_field_borrows_with_its_own_preset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    _key(tmp_path)
    prefs = _with_profiles(
        {
            "chat": {"label": "Chat", "model": "openai:gpt-test", "temperature": 0.9},
            "kb": {"label": "KB", "model": "openai:gpt-other"},
            "ex": {"label": "Ex", "model": "openai:gpt-other"},
            "ans": {"label": "Ans", "model": "openai:gpt-other"},
        },
        llm__chat_profile="chat",
    )
    # knowledge (null) → the chat job's model, with the knowledge preset tuning.
    r = resolve_job_model(prefs, tmp_path, "knowledge")
    assert r is not None
    assert (r.model_id, r.temperature, r.max_tokens, r.profile_id) == ("openai:gpt-test", 0.2, 1600, "chat")
    assert job_model_source(prefs, "knowledge") == "llm.chat_profile"
    # rewrite (null) → knowledge (null) → chat, with the rewrite preset (thinking off).
    r = resolve_job_model(prefs, tmp_path, "rewrite")
    assert r is not None and (r.model_id, r.thinking, r.max_tokens) == ("openai:gpt-test", "off", 1024)
    # vision falls back to nothing.
    assert resolve_job_model(prefs, tmp_path, "vision") is None
    assert job_model_source(prefs, "vision") is None

    prefs = _with_profiles(
        prefs.model_dump(mode="json")["ai"]["profiles"],
        llm__chat_profile="chat",
        knowledge__answering__profile="kb",
        graph__extraction_profile="ex",
    )
    assert resolve_job_model(prefs, tmp_path, "rewrite").model_id == "openai:gpt-other"
    assert job_model_source(prefs, "rewrite") == "knowledge.answering.profile"
    small = resolve_job_model(prefs, tmp_path, "graph_small")
    assert (small.model_id, small.profile_id, small.max_tokens) == ("openai:gpt-other", "ex", 2048)


def test_job_field_refuses_unknown_or_plan_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import ValidationError

    _patch_catalog(tmp_path, monkeypatch)
    with pytest.raises(ValidationError, match="llm.chat_profile points at an unknown AI profile"):
        _with_profiles({}, llm__chat_profile="ghost")
    with pytest.raises(ValidationError, match="plan tool"):
        _with_profiles({"plan": {"label": "Plan", "model": "claude_code:sonnet"}}, graph__extraction_profile="plan")
    with pytest.raises(ValidationError, match="voice.hiro_profile points at an unknown voice profile"):
        WorkspacePreferences.model_validate({"voice": {"hiro_profile": "ghost"}})
    # A plan profile may still sit in a fallback chain.
    _with_profiles(
        {"api": {"label": "API", "model": "openai:gpt-test", "fallback": "plan"},
         "plan": {"label": "Plan", "model": "claude_code:sonnet"}},
        llm__chat_profile="api",
    )


def test_resolve_knowledge_answering_llm_none_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    prefs = _with_profiles({"chat": {"label": "Chat", "model": "openai:gpt-test"}}, llm__chat_profile="chat")
    assert resolve_knowledge_answering_llm(prefs, tmp_path) is None


def test_resolve_character_llm_prefers_character_list_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    _key(tmp_path)
    prefs = _with_profiles(
        {
            "chat": {"label": "Chat", "model": "openai:gpt-test"},
            "other": {"label": "Other", "model": "openai:gpt-other", "temperature": 0.2, "max_tokens": 99},
        },
        llm__chat_profile="chat",
    )
    from hirocli.domain.preferences import resolve_character_llm

    r = resolve_character_llm(["other", "chat"], prefs, tmp_path)
    assert r is not None
    assert (r.model_id, r.temperature, r.max_tokens, r.profile_id) == ("openai:gpt-other", 0.2, 99, "other")


def test_resolve_character_llm_falls_back_when_list_unusable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Missing ids and profiles with no available model are skipped → the chat job's profile.
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    _key(tmp_path)
    prefs = _with_profiles(
        {"chat": {"label": "Chat", "model": "openai:gpt-test"}, "ds": {"label": "DS", "model": "deepseek:ds-test"}},
        llm__chat_profile="chat",
    )
    from hirocli.domain.preferences import resolve_character_llm

    r = resolve_character_llm(["ghost", "ds"], prefs, tmp_path)
    assert r is not None and (r.model_id, r.profile_id) == ("openai:gpt-test", "chat")
    no_chat = _with_profiles({"ds": {"label": "DS", "model": "deepseek:ds-test"}})
    assert resolve_character_llm(["ds"], no_chat, tmp_path) is None


def _voice_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hirocli.domain import model_catalog as mc

    doc = {
        "catalog_version": "1.0.0",
        "providers": [
            {"id": "openai", "display_name": "OpenAI", "hosting": "cloud",
             "credential_env_keys": ["OPENAI_API_KEY"], "metadata_updated_at": "2026-01-01"},
            {"id": "google", "display_name": "Google", "hosting": "cloud",
             "credential_env_keys": ["GOOGLE_API_KEY"], "metadata_updated_at": "2026-01-01"},
        ],
        "models": [
            {"id": "openai:gpt-test", "provider_id": "openai", "display_name": "G", "model_kind": "chat"},
            {"id": "openai:stt-one", "provider_id": "openai", "display_name": "STT", "model_kind": "stt"},
            {"id": "openai:tts-one", "provider_id": "openai", "display_name": "TTS One", "model_kind": "tts"},
            {"id": "google:tts-g", "provider_id": "google", "display_name": "TTS G", "model_kind": "tts"},
        ],
    }
    p = tmp_path / "cat.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    cat = ModelCatalog.load_from_path(p)
    monkeypatch.setattr(mc, "get_model_catalog", lambda: cat)
    monkeypatch.setattr("hirocli.domain.credential_store.get_model_catalog", lambda: cat)


def test_resolve_character_voice_first_profile_with_a_key_then_hiro(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 7b step 5: the character's voice profiles (first whose provider has a key), else Hiro's."""
    _fixture_workspace(tmp_path, monkeypatch)
    _voice_catalog(tmp_path, monkeypatch)
    _key(tmp_path, "openai")
    prefs = WorkspacePreferences.model_validate(
        {
            "voice": {
                "profiles": {
                    "g": {"label": "G", "model": "google:tts-g", "voice": "kore"},
                    "o": {"label": "O", "model": "openai:tts-one", "voice": "sage", "style": "calm"},
                    "hiro-voice": {"label": "Hiro's voice", "model": "openai:tts-one", "voice": "ash"},
                },
                "hiro_profile": "hiro-voice",
            }
        }
    )
    from hirocli.domain.preferences import resolve_character_voice

    r = resolve_character_voice(["ghost", "g", "o"], prefs, tmp_path)
    assert r is not None and (r.profile_id, r.source, r.profile.style) == ("o", "character", "calm")
    r = resolve_character_voice(["g"], prefs, tmp_path)
    assert r is not None and (r.profile_id, r.source) == ("hiro-voice", "hiro")
    prefs.voice.hiro_profile = None
    assert resolve_character_voice([], prefs, tmp_path) is None


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

    prefs = WorkspacePreferences.model_validate(
        {
            "llm": {"default_stt": "openai:stt-one"},
            "voice": {"profiles": {"v1": {"label": "V1", "model": "openai:tts-one", "voice": "sage"}}},
        }
    )
    prefs.media = MediaPreferences(input=ModalityFlags(voice=True), output=ModalityFlags(voice=True))
    save_preferences(tmp_path, prefs)
    create_character(
        tmp_path,
        "voice-bot",
        "Voice Bot",
        voice_profiles=["v1"],
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
