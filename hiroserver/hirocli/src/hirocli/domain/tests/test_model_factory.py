"""Tests for create_chat_model guard rails."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.model_catalog import ModelCatalog, clear_model_catalog_cache
from hirocli.domain.model_factory import catalog_embedding_dimensions, create_chat_model, create_embedding_model


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
        ],
        "models": [
            {
                "id": "openai:gpt-5.4",
                "provider_id": "openai",
                "display_name": "GPT 5.4",
                "model_kind": "chat",
                "model_class": "reasoning",
                "features": ["reasoning"],
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
    assert model.reasoning_effort == "minimal"
    assert "max_tokens" not in model._default_params


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
