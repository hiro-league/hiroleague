"""Tests for Phase 3c onboarding default suggestions."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hirocli.domain.available_models import AvailableModelsService
from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.model_catalog import ModelCatalog, clear_model_catalog_cache
from hirocli.domain.onboarding_defaults import (
    apply_onboarding_defaults_to_preferences,
    apply_suggested_defaults,
    compute_suggested_defaults,
)
from hirocli.domain.preferences import LLMPreferences, WorkspacePreferences


@pytest.fixture(autouse=True)
def _clear_catalog_cache() -> None:
    clear_model_catalog_cache()
    yield
    clear_model_catalog_cache()


def _minimal_catalog(tmp_path: Path) -> ModelCatalog:
    doc = {
        "catalog_version": 99,
        "providers": [
            {
                "id": "a",
                "display_name": "A",
                "hosting": "cloud",
                "credential_env_keys": ["KA"],
                "metadata_updated_at": "2026-01-01",
                "recommended_models": {"chat": "a:chat1"},
            },
            {
                "id": "b",
                "display_name": "B",
                "hosting": "cloud",
                "credential_env_keys": ["KB"],
                "metadata_updated_at": "2026-01-01",
                "recommended_models": {"chat": "b:chat1"},
            },
        ],
        "models": [
            {
                "id": "a:chat1",
                "provider_id": "a",
                "display_name": "A1",
                "model_kind": "chat",
            },
            {
                "id": "b:chat1",
                "provider_id": "b",
                "display_name": "B1",
                "model_kind": "chat",
            },
        ],
    }
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return ModelCatalog.load_from_path(p)


def test_compute_first_provider_wins_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cat = _minimal_catalog(tmp_path)
    monkeypatch.setattr(
        "hirocli.domain.credential_store.get_model_catalog",
        lambda: cat,
    )
    store = CredentialStore(
        tmp_path / "ws",
        "wid",
        _test_secrets={("hiroleague:wid:a", "api_key"): "k", ("hiroleague:wid:b", "api_key"): "k"},
    )
    store.set_api_key("a", "x")
    store.set_api_key("b", "y")
    ams = AvailableModelsService(cat, store)
    prefs = LLMPreferences()
    suggestions = compute_suggested_defaults(["a", "b"], cat, ams, prefs)
    assert len(suggestions) == 1
    assert suggestions[0].model_id == "a:chat1"


def test_compute_skips_filled_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cat = _minimal_catalog(tmp_path)
    monkeypatch.setattr(
        "hirocli.domain.credential_store.get_model_catalog",
        lambda: cat,
    )
    store = CredentialStore(
        tmp_path / "ws",
        "wid",
        _test_secrets={("hiroleague:wid:a", "api_key"): "k"},
    )
    store.set_api_key("a", "x")
    ams = AvailableModelsService(cat, store)
    prefs = LLMPreferences(default_chat="manual:chat")
    suggestions = compute_suggested_defaults(["a"], cat, ams, prefs)
    assert suggestions == []


def test_apply_sets_summarization_with_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cat = _minimal_catalog(tmp_path)
    monkeypatch.setattr(
        "hirocli.domain.credential_store.get_model_catalog",
        lambda: cat,
    )
    store = CredentialStore(
        tmp_path / "ws",
        "wid",
        _test_secrets={("hiroleague:wid:a", "api_key"): "k"},
    )
    store.set_api_key("a", "x")
    ams = AvailableModelsService(cat, store)
    prefs = WorkspacePreferences()
    suggestions = compute_suggested_defaults(["a"], cat, ams, prefs.llm)
    applied = apply_suggested_defaults(prefs, suggestions)
    assert len(applied) == 1
    assert prefs.llm.default_chat == "a:chat1"
    assert prefs.llm.default_summarization == "a:chat1"


def test_apply_onboarding_defaults_to_preferences_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cat = _minimal_catalog(tmp_path)
    monkeypatch.setattr(
        "hirocli.domain.credential_store.get_model_catalog",
        lambda: cat,
    )
    monkeypatch.setattr(
        "hirocli.domain.onboarding_defaults.get_model_catalog",
        lambda: cat,
    )
    ws = tmp_path / "ws"
    store = CredentialStore(
        ws,
        "wid",
        _test_secrets={("hiroleague:wid:a", "api_key"): "k"},
    )
    store.set_api_key("a", "x")
    # Use bundled prefs path
    applied = apply_onboarding_defaults_to_preferences(ws, "wid", ["a"])
    assert applied
    from hirocli.domain.preferences import load_preferences

    prefs2 = load_preferences(ws)
    assert prefs2.llm.default_chat == "a:chat1"
