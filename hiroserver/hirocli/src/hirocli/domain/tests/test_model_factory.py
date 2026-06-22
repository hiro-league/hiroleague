"""Tests for create_chat_model guard rails."""

from __future__ import annotations

from pathlib import Path

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
                "id": "openai:gpt-5.4",
                "provider_id": "openai",
                "display_name": "GPT 5.4",
                "model_kind": "chat",
                "model_class": "reasoning",
                "features": ["reasoning"],
                # GPT-5.4 generation dropped `minimal`, added `none`/`xhigh`.
                "reasoning_efforts": ["none", "low", "medium", "high", "xhigh"],
            },
            {
                # GPT-5.0 generation still has `minimal`, lacks `none`/`xhigh`.
                "id": "openai:gpt-5",
                "provider_id": "openai",
                "display_name": "GPT 5",
                "model_kind": "chat",
                "model_class": "reasoning",
                "features": ["reasoning"],
                "reasoning_efforts": ["minimal", "low", "medium", "high"],
            },
            {
                # Pro tier — high only; every enabled level clamps up to high.
                "id": "openai:gpt-5-pro",
                "provider_id": "openai",
                "display_name": "GPT 5 pro",
                "model_kind": "chat",
                "model_class": "reasoning",
                "features": ["reasoning"],
                "reasoning_efforts": ["high"],
            },
            {
                "id": "google:gemini-3-flash-preview",
                "provider_id": "google",
                "display_name": "Gemini 3 Flash Preview",
                "model_kind": "chat",
                "model_class": "balanced",
                "features": ["reasoning"],
            },
            {
                "id": "deepseek:deepseek-v4-flash",
                "provider_id": "deepseek",
                "display_name": "DeepSeek V4 Flash",
                "model_kind": "chat",
                "model_class": "fast",
                "features": ["tools", "structured_output", "reasoning"],
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
                "id": "ollama:llama3.3",
                "provider_id": "ollama",
                "display_name": "Llama 3.3",
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
            "openai:gpt-5.4",
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
        "openai:gpt-5.4",
        workspace_path=tmp_path,
        credential_store=store,
        max_tokens=4096,
        thinking="minimal",
    )

    assert model._default_params["model"] == "gpt-5.4"
    assert model._default_params["max_completion_tokens"] == 4096
    # GPT-5.4 dropped `minimal` (live API 400s on it) — neutral `minimal` clamps up to `low`.
    assert model.reasoning_effort == "low"
    assert "max_tokens" not in model._default_params
    # Reasoning models must route through the Responses API — /v1/chat/completions 400s on
    # reasoning_effort + function tools for GPT-5.x.
    assert model.use_responses_api is True


def test_openai_minimal_passes_through_on_gpt5_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_api_key("openai", "sk-test")

    # GPT-5.0 keeps `minimal` in its vocabulary, so it is sent verbatim (no clamp).
    model = create_chat_model(
        "openai:gpt-5", workspace_path=tmp_path, credential_store=store, thinking="minimal",
    )
    assert model.reasoning_effort == "minimal"


def test_openai_off_maps_to_none_when_supported_else_omits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_api_key("openai", "sk-test")

    # gpt-5.4 has an explicit `none` effort → `off` maps to it.
    model_none = create_chat_model(
        "openai:gpt-5.4", workspace_path=tmp_path, credential_store=store, thinking="off",
    )
    assert model_none.reasoning_effort == "none"

    # gpt-5.0 has no `none` → `off` omits reasoning_effort (model applies its default effort).
    model_omit = create_chat_model(
        "openai:gpt-5", workspace_path=tmp_path, credential_store=store, thinking="off",
    )
    assert model_omit.reasoning_effort is None


def test_openai_pro_clamps_every_level_up_to_high(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_api_key("openai", "sk-test")

    # Pro tier accepts `high` only; a sub-high request clamps up rather than 400ing.
    model = create_chat_model(
        "openai:gpt-5-pro", workspace_path=tmp_path, credential_store=store, thinking="low",
    )
    assert model.reasoning_effort == "high"


def test_google_thinking_level_maps_for_gemini_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_api_key("google", "gk-test")

    model = create_chat_model(
        "google:gemini-3-flash-preview",
        workspace_path=tmp_path,
        credential_store=store,
        temperature=0,
        max_tokens=8192,
        thinking="low",
    )

    assert model.model == "gemini-3-flash-preview"
    assert model.thinking_level == "low"
    assert model.max_output_tokens == 8192


def test_deepseek_thinking_enables_reasoning_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_api_key("deepseek", "ds-test")

    model = create_chat_model(
        "deepseek:deepseek-v4-flash",
        workspace_path=tmp_path,
        credential_store=store,
        temperature=0.7,
        max_tokens=4096,
        thinking="high",
    )

    assert model.model_name == "deepseek-v4-flash"
    assert str(model.api_base).startswith("https://api.deepseek.com")
    # high → "max"; thinking enabled and temperature NOT sent (DeepSeek ignores it in thinking mode).
    assert model.reasoning_effort == "max"
    assert model.extra_body == {"thinking": {"type": "enabled"}}


def test_deepseek_off_disables_thinking_and_keeps_temperature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wid = _registry(monkeypatch, tmp_path)
    _patch_catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, wid, _test_secrets={})
    store.set_api_key("deepseek", "ds-test")

    model = create_chat_model(
        "deepseek:deepseek-v4-flash",
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

    # llama3.3 lacks the `reasoning` catalog feature, so the think flag must not be sent even
    # when a thinking level is requested.
    model = create_chat_model(
        "ollama:llama3.3",
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
    assert calls["kwargs"] == {"api_key": "sk-test"}
