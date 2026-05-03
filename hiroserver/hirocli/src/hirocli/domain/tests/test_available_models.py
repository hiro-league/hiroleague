"""Tests for AvailableModelsService."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hirocli.domain.available_models import AvailableModelsService, build_available_models_service
from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.model_catalog import ModelCatalog, clear_model_catalog_cache


@pytest.fixture(autouse=True)
def _clear_cat() -> None:
    clear_model_catalog_cache()
    yield
    clear_model_catalog_cache()


def _minimal_catalog(tmp_path: Path) -> ModelCatalog:
    doc = {
        "catalog_version": "1.0.0",
        "providers": [
            {
                "id": "pa",
                "display_name": "PA",
                "hosting": "cloud",
                "credential_env_keys": ["PA_KEY"],
                "metadata_updated_at": "2026-01-01",
            },
            {
                "id": "pb",
                "display_name": "PB",
                "hosting": "cloud",
                "credential_env_keys": ["PB_KEY"],
                "metadata_updated_at": "2026-01-01",
            },
        ],
        "models": [
            {
                "id": "pa:chat1",
                "provider_id": "pa",
                "display_name": "Chat1",
                "model_kind": "chat",
            },
            {
                "id": "pa:tts1",
                "provider_id": "pa",
                "display_name": "T1",
                "model_kind": "tts",
            },
            {
                "id": "pb:chat2",
                "provider_id": "pb",
                "display_name": "Chat2",
                "model_kind": "chat",
            },
        ],
    }
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return ModelCatalog.load_from_path(p)


def test_list_available_only_configured_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cat = _minimal_catalog(tmp_path)
    monkeypatch.setattr("hirocli.domain.credential_store.get_model_catalog", lambda: cat)
    secrets: dict[tuple[str, str], str] = {}
    store = CredentialStore(tmp_path, "w1", _test_secrets=secrets)
    store.set_api_key("pa", "key")
    ams = AvailableModelsService(cat, store)
    ids = {m.id for m in ams.list_available_models()}
    assert ids == {"pa:chat1", "pa:tts1"}
    assert not ams.is_model_available("pb:chat2")


def test_validate_character_models_buckets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cat = _minimal_catalog(tmp_path)
    monkeypatch.setattr("hirocli.domain.credential_store.get_model_catalog", lambda: cat)
    secrets: dict[tuple[str, str], str] = {}
    store = CredentialStore(tmp_path, "w1", _test_secrets=secrets)
    store.set_api_key("pa", "k")
    ams = AvailableModelsService(cat, store)
    vr = ams.validate_character_models(
        llm_models=["pa:chat1", "nope:x", "pa:tts1", "pb:chat2"],
        voice_models=["pa:tts1", "pa:chat1", "ghost:y"],
    )
    assert "nope:x" in vr.unknown_llm
    assert "pa:tts1" in vr.wrong_kind_llm
    assert "pb:chat2" in vr.unavailable_llm
    assert "ghost:y" in vr.unknown_voice
    assert "pa:chat1" in vr.wrong_kind_voice


def test_build_available_models_service_matches_explicit_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cat = _minimal_catalog(tmp_path)
    monkeypatch.setattr("hirocli.domain.credential_store.get_model_catalog", lambda: cat)
    monkeypatch.setattr("hirocli.domain.available_models.get_model_catalog", lambda: cat)
    secrets: dict[tuple[str, str], str] = {}
    store = CredentialStore(tmp_path, "w1", _test_secrets=secrets)
    store.set_api_key("pa", "k")
    explicit = AvailableModelsService(cat, store)
    built = build_available_models_service(tmp_path, "w1", store=store)
    assert built.list_available_models() == explicit.list_available_models()


def test_validate_deprecated_llm_not_also_wrong_kind_or_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = {
        "catalog_version": "1.0.0",
        "providers": [
            {
                "id": "pa",
                "display_name": "PA",
                "hosting": "cloud",
                "credential_env_keys": ["PA_KEY"],
                "metadata_updated_at": "2026-01-01",
            },
        ],
        "models": [
            {
                "id": "pa:new-tts",
                "provider_id": "pa",
                "display_name": "New",
                "model_kind": "tts",
            },
            {
                "id": "pa:old-tts",
                "provider_id": "pa",
                "display_name": "Old",
                "model_kind": "tts",
                "deprecated_since": "2026-02-01",
                "replacement_id": "pa:new-tts",
            },
        ],
    }
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    cat = ModelCatalog.load_from_path(p)
    monkeypatch.setattr("hirocli.domain.credential_store.get_model_catalog", lambda: cat)
    secrets: dict[tuple[str, str], str] = {}
    store = CredentialStore(tmp_path, "w1", _test_secrets=secrets)
    store.set_api_key("pa", "k")
    ams = AvailableModelsService(cat, store)
    vr = ams.validate_character_models(llm_models=["pa:old-tts"], voice_models=[])
    assert any(d.model_id == "pa:old-tts" for d in vr.deprecated_llm)
    assert "pa:old-tts" not in vr.wrong_kind_llm
    assert "pa:old-tts" not in vr.unavailable_llm
