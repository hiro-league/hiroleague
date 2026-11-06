"""Tests for create_chat_model guard rails."""

from __future__ import annotations

from pathlib import Path

import httpx2
import pytest
import yaml

from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.model_catalog import ModelCatalog, clear_model_catalog_cache
from hirocli.domain.model_factory import (
    catalog_embedding_dimensions,
    create_chat_model,
    create_embedding_model,
    with_structured_output_compat,
)


@pytest.fixture(autouse=True)
def _clear_cat() -> None:
    clear_model_catalog_cache()
    yield
    clear_model_catalog_cache()


def _registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    from hirocli.domain import workspace as ws_mod

    wid = "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee"
    reg = ws_mod.WorkspaceRegistry(
        default_workspace=wid,
        workspaces={
            wid: ws_mod.WorkspaceEntry(
                id=wid,
                name="tf",
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
            {
                "id": "google",
                "display_name": "Google",
                "hosting": "cloud",
                "credential_env_keys": ["GOOGLE_API_KEY"],
                "metadata_updated_at": "2026-01-01",
            },
            {
                "id": "anthropic",
                "display_name": "Anthropic",
                "hosting": "cloud",
                "credential_env_keys": ["ANTHROPIC_API_KEY"],
                "metadata_updated_at": "2026-01-01",
            },
            {
                "id": "deepseek",
                "display_name": "DeepSeek",
                "hosting": "cloud",
                "credential_env_keys": ["DEEPSEEK_API_KEY"],
                "default_base_url": "https://api.deepseek.com",
                "metadata_updated_at": "2026-01-01",
            },
            {
                "id": "ollama",
                "display_name": "Ollama (local)",
                "hosting": "local",
                "default_base_url": "http://localhost:11434",
                "metadata_updated_at": "2026-01-01",
            },
        ],
        "models": [
            {
                # GPT-6.1 Terra / 6 Luna: none..max (no `minimal`).
                "id": "openai:gpt-6.1-terra",
                "provider_id": "openai",
                "display_name": "GPT-6.1 Terra",
                "model_kind": "chat",
                "model_class": "balanced",
                "features": ["reasoning"],
                "reasoning_efforts": ["none", "low", "medium", "high", "xhigh", "max"],
            },
            {
                # GPT-6 Astra / 6.1 Sol: no `none` either.
                "id": "openai:gpt-6.1-sol",
                "provider_id": "openai",
                "display_name": "GPT-6.1 Sol",
                "model_kind": "chat",
                "model_class": "agentic",
                "features": ["reasoning"],
                "reasoning_efforts": ["low", "medium", "high", "xhigh", "max"],
            },
            {
                # Gemini 3.8 Flash: `minimal` is an error.
                "id": "google:gemini-3.8-flash",
                "provider_id": "google",
                "display_name": "Gemini 3.8 Flash",
                "model_kind": "chat",
                "model_class": "balanced",
                "features": ["reasoning"],
                "reasoning_efforts": ["low", "medium", "high"],
            },
            {
                "id": "google:gemini-3.5-flash-lite",
                "provider_id": "google",
                "display_name": "Gemini 3.5 Flash-Lite",
                "model_kind": "chat",
                "model_class": "fast",
                "features": ["reasoning"],
                "reasoning_efforts": ["minimal", "low", "medium", "high"],
            },
            {
                "id": "anthropic:claude-opus-5-5",
                "provider_id": "anthropic",
                "display_name": "Claude Opus 5.5",
                "model_kind": "chat",
                "model_class": "reasoning",
                "features": ["tools", "reasoning"],
                "reasoning_efforts": ["low", "medium", "high", "xhigh", "max"],
            },
            {
                "id": "anthropic:claude-sonnet-5-5",
                "provider_id": "anthropic",
                "display_name": "Claude Sonnet 5.5",
                "model_kind": "chat",
                "model_class": "agentic",
                "features": ["tools", "reasoning"],
                "reasoning_efforts": ["low", "medium", "high", "xhigh", "max"],
                "thinking_off_type": "between_tools",
            },
            {
                "id": "anthropic:claude-haiku-5-5",
                "provider_id": "anthropic",
                "display_name": "Claude Haiku 5.5",
                "model_kind": "chat",
                "model_class": "fast",
                "features": ["tools", "reasoning"],
                "reasoning_efforts": ["low", "medium", "high", "xhigh", "max"],
                "thinking_off_type": "disabled",
            },
            {
                "id": "deepseek:deepseek-flash",
                "provider_id": "deepseek",
                "display_name": "DeepSeek Flash",
                "model_kind": "chat",
                "model_class": "fast",
                "features": ["tools", "structured_output", "reasoning"],
                "reasoning_efforts": ["low", "high", "max"],
            },
            {
                "id": "openai:text-embedding-3-small",
                "provider_id": "openai",
                "display_name": "text-embedding-3-small",
                "model_kind": "embedding",
            },
            {
                # Colon in the api id (gemma4:12b) exercises split-on-first-colon id handling.
                "id": "ollama:gemma4:12b",
                "provider_id": "ollama",
                "display_name": "Gemma 4 12B",
                "model_kind": "chat",
                "model_class": "balanced",
                "features": ["tools", "structured_output", "reasoning"],
            },
            {
                # A local model without the `reasoning` feature.
                "id": "ollama:plain-model",
                "provider_id": "ollama",
                "display_name": "Plain local model",
                "model_kind": "chat",
                "model_class": "agentic",
                "features": ["tools", "streaming"],
            },
        ],
    }
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    cat = ModelCatalog.load_from_path(path)
    monkeypatch.setattr(mc, "get_model_catalog", lambda: cat)
    monkeypatch.setattr("hirocli.domain.model_factory.get_model_catalog", lambda: cat)
    monkeypatch.setattr("hirocli.domain.credential_store.get_model_catalog", lambda: cat)


def test_unknown_model_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _registry(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="Unknown model"):
        create_chat_model(
            "openai:definitely-not-in-catalog-xyz",
            workspace_path=tmp_path,
        )


def test_unconfigured_provider_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _registry(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="not configured"):
        create_chat_model(
            "openai:gpt-6.1-terra",
            workspace_path=tmp_path,
        )


def test_openai_reasoning_uses_completion_tokens_and_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_api_key("openai", "sk-test")

    model = create_chat_model(
        "openai:gpt-6.1-terra",
        workspace_path=tmp_path,
        credential_store=store,
        max_tokens=4096,
        thinking="minimal",
    )

    assert model._default_params["model"] == "gpt-6.1-terra"
    assert model._default_params["max_completion_tokens"] == 4096
    # No GPT-5.6/6 model accepts `minimal` — neutral `minimal` clamps up to `low` (not `none`).
    assert model.reasoning_effort == "low"
    assert "max_tokens" not in model._default_params
    # Reasoning models must route through the Responses API — GPT-6 rejects tool calling on
    # /v1/chat/completions ("Tool calling requires the Responses API").
    assert model.use_responses_api is True
    # Reasoning models never get a temperature.
    assert model.temperature is None


def test_openai_off_maps_to_none_when_supported_else_omits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_api_key("openai", "sk-test")

    # 6.1 Terra has an explicit `none` effort → `off` maps to it.
    model_none = create_chat_model(
        "openai:gpt-6.1-terra", workspace_path=tmp_path, credential_store=store, thinking="off",
    )
    assert model_none.reasoning_effort == "none"

    # 6.1 Sol has no `none` → `off` omits reasoning_effort (model applies its default effort).
    model_omit = create_chat_model(
        "openai:gpt-6.1-sol", workspace_path=tmp_path, credential_store=store, thinking="off",
    )
    assert model_omit.reasoning_effort is None


def test_google_thinking_level_clamps_to_model_levels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_api_key("google", "gk-test")

    model = create_chat_model(
        "google:gemini-3.8-flash",
        workspace_path=tmp_path,
        credential_store=store,
        temperature=0,
        max_tokens=8192,
        thinking="minimal",
    )

    assert model.model == "gemini-3.8-flash"
    # `minimal` is an error on 3.8 Flash → clamps up to `low`.
    assert model.thinking_level == "low"
    assert model.max_output_tokens == 8192
    # Sampling params are deprecated on Gemini — never sent.
    assert model.temperature is None


def test_google_off_maps_to_lowest_level(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_api_key("google", "gk-test")

    # Gemini 3.x can't turn thinking fully off: `off` → the model's lowest level.
    flash = create_chat_model(
        "google:gemini-3.8-flash", workspace_path=tmp_path, credential_store=store, thinking="off",
    )
    assert flash.thinking_level == "low"
    lite = create_chat_model(
        "google:gemini-3.5-flash-lite", workspace_path=tmp_path, credential_store=store, thinking="off",
    )
    assert lite.thinking_level == "minimal"
    assert lite.thinking_budget is None


def _anthropic_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, model_id: str, **kw):
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_api_key("anthropic", "sk-ant-test")
    return create_chat_model(model_id, workspace_path=tmp_path, credential_store=store, **kw)


def test_anthropic_sends_adaptive_thinking_and_effort_never_temperature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _anthropic_model(
        tmp_path, monkeypatch, "anthropic:claude-opus-5-5",
        temperature=0.7, max_tokens=4096, thinking="minimal",
    )
    # API version 2026-10-21 (anthropic 2.x) rejects temperature on every model.
    assert model.temperature is None
    assert model.max_tokens == 4096
    # enabled+budget_tokens is a 400 on Claude 5.x — adaptive thinking + effort instead.
    assert model.thinking == {"type": "adaptive"}
    assert model.effort == "low"  # `minimal` is not a Claude effort → clamps up to low
    params = model._get_request_payload("hi")
    assert "temperature" not in params
    assert params["output_config"] == {"effort": "low"}

    high = _anthropic_model(tmp_path, monkeypatch, "anthropic:claude-opus-5-5", thinking="high")
    assert high.effort == "high"


def test_anthropic_off_uses_model_specific_off_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Sonnet 5.5 rejects "disabled"; its lowest setting is "between_tools".
    sonnet = _anthropic_model(tmp_path, monkeypatch, "anthropic:claude-sonnet-5-5", thinking="off")
    assert sonnet.thinking == {"type": "between_tools"}
    assert sonnet.effort is None
    # Haiku 5.5 accepts "disabled".
    haiku = _anthropic_model(tmp_path, monkeypatch, "anthropic:claude-haiku-5-5", thinking="off")
    assert haiku.thinking == {"type": "disabled"}
    # Opus 5.5 cannot turn thinking off → adaptive at its lowest effort.
    opus = _anthropic_model(tmp_path, monkeypatch, "anthropic:claude-opus-5-5", thinking="off")
    assert opus.thinking == {"type": "adaptive"}
    assert opus.effort == "low"


def test_anthropic_no_thinking_level_sends_model_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _anthropic_model(tmp_path, monkeypatch, "anthropic:claude-sonnet-5-5")
    assert model.thinking is None
    assert model.effort is None


def test_deepseek_thinking_enables_reasoning_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_api_key("deepseek", "ds-test")

    model = create_chat_model(
        "deepseek:deepseek-flash",
        workspace_path=tmp_path,
        credential_store=store,
        temperature=0.7,
        max_tokens=4096,
        thinking="high",
    )

    assert model.model_name == "deepseek-flash"
    assert str(model.api_base).startswith("https://api.deepseek.com")
    # high → "max"; thinking enabled and temperature NOT sent (DeepSeek ignores it in thinking mode).
    assert model.reasoning_effort == "max"
    assert model.extra_body == {"thinking": {"type": "enabled"}}

    # DeepSeek added a `low` effort (Aug 2026): low → low, medium → high.
    low = create_chat_model(
        "deepseek:deepseek-flash", workspace_path=tmp_path, credential_store=store, thinking="low",
    )
    assert low.reasoning_effort == "low"
    medium = create_chat_model(
        "deepseek:deepseek-flash", workspace_path=tmp_path, credential_store=store, thinking="medium",
    )
    assert medium.reasoning_effort == "high"


def test_deepseek_off_disables_thinking_and_keeps_temperature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_api_key("deepseek", "ds-test")

    model = create_chat_model(
        "deepseek:deepseek-flash",
        workspace_path=tmp_path,
        credential_store=store,
        temperature=0.2,
        max_tokens=1024,
        thinking="off",
    )

    # Non-thinking mode: temperature honored, thinking explicitly disabled, no effort.
    assert model.temperature == 0.2
    assert model.extra_body == {"thinking": {"type": "disabled"}}
    assert model.reasoning_effort is None


def test_ollama_reasoning_on_sets_think_and_num_ctx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_local_endpoint("ollama", "http://localhost:11434")

    model = create_chat_model(
        "ollama:gemma4:12b",
        workspace_path=tmp_path,
        credential_store=store,
        temperature=0.5,
        max_tokens=2048,
        thinking="medium",
        num_ctx=8192,
    )

    # api id is everything after the FIRST colon — the gemma4 tag's own colon is preserved.
    assert model.model == "gemma4:12b"
    assert str(model.base_url) == "http://localhost:11434"
    assert model.num_predict == 2048
    # Any enabled ThinkingLevel maps to the boolean think flag (Gemma 4 has no graded effort).
    assert model.reasoning is True
    assert model.num_ctx == 8192


def test_ollama_reasoning_off_disables_think(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_local_endpoint("ollama", "http://localhost:11434")

    model = create_chat_model(
        "ollama:gemma4:12b",
        workspace_path=tmp_path,
        credential_store=store,
        thinking="off",
    )

    assert model.reasoning is False
    # num_ctx not passed → Ollama's own default applies (we never auto-max the catalog window).
    assert model.num_ctx is None


def test_ollama_non_reasoning_model_omits_think_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_local_endpoint("ollama", "http://localhost:11434")

    # This model lacks the `reasoning` catalog feature, so the think flag must not be sent even
    # when a thinking level is requested.
    model = create_chat_model(
        "ollama:plain-model",
        workspace_path=tmp_path,
        credential_store=store,
        thinking="high",
    )

    assert model.reasoning is None


def test_with_structured_output_compat_deepseek_thinking_uses_json_mode() -> None:
    """DeepSeek THINKING models get method=json_mode (forced tool_choice 400s in thinking mode);
    non-thinking DeepSeek and every other model class keep langchain's default method."""

    class ChatDeepSeek:  # noqa: N801 — the helper keys on this class name.
        def __init__(self, extra_body: dict | None) -> None:
            self.extra_body = extra_body
            self.calls: list[dict] = []

        def with_structured_output(self, schema, include_raw=False, **kwargs):  # noqa: ANN001
            self.calls.append({"schema": schema, "include_raw": include_raw, **kwargs})
            return "structured"

    thinking = ChatDeepSeek({"thinking": {"type": "enabled"}})
    assert with_structured_output_compat(thinking, dict) == "structured"
    assert thinking.calls[0]["method"] == "json_mode"
    assert thinking.calls[0]["include_raw"] is True

    flat = ChatDeepSeek({"thinking": {"type": "disabled"}})
    with_structured_output_compat(flat, dict)
    assert "method" not in flat.calls[0]

    class OtherModel(ChatDeepSeek):  # different class name → default method even if "thinking"
        pass

    other = OtherModel({"thinking": {"type": "enabled"}})
    with_structured_output_compat(other, dict)
    assert "method" not in other.calls[0]

    # A DeepSeek model built without extra_body (None) must not crash and keeps the default method.
    no_extra = ChatDeepSeek(None)
    with_structured_output_compat(no_extra, dict)
    assert "method" not in no_extra.calls[0]

    # include_raw=False is forwarded verbatim (not silently overridden to True).
    explicit = ChatDeepSeek({"thinking": {"type": "enabled"}})
    with_structured_output_compat(explicit, dict, include_raw=False)
    assert explicit.calls[0]["include_raw"] is False
    assert explicit.calls[0]["method"] == "json_mode"


def test_create_embedding_model_openai(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_api_key("openai", "sk-test")

    model = create_embedding_model(
        "openai:text-embedding-3-small",
        workspace_path=tmp_path,
        credential_store=store,
    )

    assert model.model == "text-embedding-3-small"
    assert catalog_embedding_dimensions("openai:text-embedding-3-small") == 1536


def test_create_embedding_model_delegates_to_init_embeddings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_api_key("openai", "sk-test")
    calls: dict[str, object] = {}

    def fake_init_embeddings(model: str, *, provider: str | None = None, **kwargs: object) -> object:
        calls["model"] = model
        calls["provider"] = provider
        calls["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("hirocli.domain.model_factory.init_embeddings", fake_init_embeddings)

    create_embedding_model(
        "openai:text-embedding-3-small",
        workspace_path=tmp_path,
        credential_store=store,
    )

    assert calls["model"] == "openai:text-embedding-3-small"
    assert calls["provider"] is None
    kwargs = calls["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["api_key"] == "sk-test"
    # A warm-keepalive http_client is injected so human-paced chat turns don't re-handshake on
    # every query embed (see _embedding_provider_kwargs); assert it's wired with our keepalive.
    http_client = kwargs["http_client"]
    assert isinstance(http_client, httpx2.Client)
    assert http_client.timeout.read == 30.0
    assert set(kwargs) == {"api_key", "http_client"}


def test_openai_chat_model_gets_warm_keepalive_http_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chat models are also wired through the centralized keepalive policy (both sync + async
    clients), so the first call of each human-paced turn doesn't re-handshake."""
    from hirocli.domain.model_http import KEEPALIVE_EXPIRY_S

    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_api_key("openai", "sk-test")

    model = create_chat_model(
        "openai:gpt-6.1-terra", workspace_path=tmp_path, credential_store=store,
    )

    assert isinstance(model.http_client, httpx2.Client)
    assert isinstance(model.http_async_client, httpx2.AsyncClient)
    # The async client is the chat hot path (langchain streams over it); assert the pool keepalive.
    pool = model.http_async_client._transport._pool
    assert pool._keepalive_expiry == KEEPALIVE_EXPIRY_S


def _store_with_keys(tmp_path: Path, wid: str) -> CredentialStore:
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    for pid, key in (("openai", "sk-t"), ("google", "gk-t"), ("anthropic", "ak-t"), ("deepseek", "dk-t")):
        store.set_api_key(pid, key)
    return store


def test_cloud_chat_models_use_the_workspace_timeout_and_retry_prefs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """llm.request_timeout_s / llm.max_retries reach every cloud chat provider (one policy, not each
    SDK's own default — Gemini's was no timeout + 6 attempts)."""
    from hirocli.domain.preferences import WorkspacePreferences
    from hirocli.domain.preferences.io import save_preferences

    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = _store_with_keys(tmp_path, wid)
    prefs = WorkspacePreferences()
    prefs.llm.request_timeout_s = 45
    prefs.llm.max_retries = 1
    save_preferences(tmp_path, prefs)

    def build(mid: str):
        return create_chat_model(mid, workspace_path=tmp_path, credential_store=store)

    google = build("google:gemini-3.8-flash")
    assert google.timeout == 45
    assert google.max_retries == 2  # google-genai counts attempts, first try included

    claude = build("anthropic:claude-sonnet-5-5")
    assert claude.default_request_timeout == 45
    assert claude.max_retries == 1

    for mid in ("openai:gpt-6.1-terra", "deepseek:deepseek-flash"):
        m = build(mid)
        assert m.max_retries == 1, mid
        assert m.http_async_client.timeout.read == 45, mid


def test_cloud_chat_policy_defaults_without_prefs_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = _store_with_keys(tmp_path, wid)

    google = create_chat_model("google:gemini-3.8-flash", workspace_path=tmp_path, credential_store=store)
    assert google.timeout == 180
    assert google.max_retries == 3


def test_with_structured_output_compat_anthropic_uses_native_json_schema() -> None:
    """Claude 5.x rejects forced tool_choice, so the tool-calling method can come back as plain text;
    the helper asks for Claude's native structured outputs (method=json_schema) instead."""

    class ChatAnthropic:  # noqa: N801 — the helper keys on this class name.
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def with_structured_output(self, schema, include_raw=False, **kwargs):  # noqa: ANN001
            self.calls.append({"include_raw": include_raw, **kwargs})
            return "structured"

    claude = ChatAnthropic()
    assert with_structured_output_compat(claude, dict) == "structured"
    assert claude.calls == [{"include_raw": True, "method": "json_schema"}]
