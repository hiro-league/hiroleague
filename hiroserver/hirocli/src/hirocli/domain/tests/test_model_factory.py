"""Tests for create_chat_model guard rails."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.model_catalog import ModelCatalog, clear_model_catalog_cache
from hirocli.domain.model_factory import create_chat_model


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
