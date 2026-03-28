"""Tests for bundled LLM catalog loading and queries."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hirocli.domain.model_catalog import (
    ModelCatalog,
    clear_model_catalog_cache,
    get_model_catalog,
)


@pytest.fixture(autouse=True)
def _clear_catalog_cache() -> None:
    clear_model_catalog_cache()
    yield
    clear_model_catalog_cache()


def test_bundled_catalog_loads() -> None:
    cat = get_model_catalog()
    assert cat.catalog_version >= 2
    assert cat.get_provider("openai") is not None
    assert cat.get_model("openai:gpt-5.4") is not None


def test_list_models_filter_hosting() -> None:
    cat = get_model_catalog()
    cloud = cat.list_models(hosting="cloud")
    local = cat.list_models(hosting="local")
    assert all(
        cat.get_provider(m.provider_id) and cat.get_provider(m.provider_id).hosting == "cloud"
        for m in cloud
    )
    assert all(
        cat.get_provider(m.provider_id) and cat.get_provider(m.provider_id).hosting == "local"
        for m in local
    )
    assert len(cloud) > 0 and len(local) > 0


def test_list_credential_env_keys_unique_sorted() -> None:
    cat = get_model_catalog()
    keys = cat.list_credential_env_keys()
    assert keys == sorted(set(keys))
    assert "OPENAI_API_KEY" in keys


def test_validate_model_ids_buckets(tmp_path: Path) -> None:
    doc = {
        "catalog_version": 99,
        "providers": [
            {
                "id": "p1",
                "display_name": "P1",
                "hosting": "cloud",
                "credential_env_keys": ["K1"],
                "metadata_updated_at": "2026-01-01",
            }
        ],
        "models": [
            {
                "id": "p1:old",
                "provider_id": "p1",
                "display_name": "Old",
                "model_kind": "chat",
                "deprecated_since": "2026-01-01",
                "replacement_id": "p1:new",
            },
            {
                "id": "p1:new",
                "provider_id": "p1",
                "display_name": "New",
                "model_kind": "chat",
            },
        ],
    }
    path = tmp_path / "cat.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    cat = ModelCatalog.load_from_path(path)
    vr = cat.validate_model_ids(["p1:new", "p1:old", "missing:foo"])
    assert vr.known == ["p1:new"]
    assert vr.unknown == ["missing:foo"]
    assert len(vr.deprecated) == 1
    assert vr.deprecated[0].model_id == "p1:old"
    assert vr.deprecated[0].replacement_id == "p1:new"


def test_invalid_provider_reference_rejected(tmp_path: Path) -> None:
    doc = {
        "catalog_version": 1,
        "providers": [
            {
                "id": "only",
                "display_name": "Only",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
            }
        ],
        "models": [
            {
                "id": "other:bad",
                "provider_id": "other",
                "display_name": "Bad",
                "model_kind": "chat",
            }
        ],
    }
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown provider_id"):
        ModelCatalog.load_from_path(path)


def test_model_id_must_match_provider_prefix(tmp_path: Path) -> None:
    doc = {
        "catalog_version": 1,
        "providers": [
            {
                "id": "openai",
                "display_name": "OpenAI",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
            }
        ],
        "models": [
            {
                "id": "wrong:gpt-4",
                "provider_id": "openai",
                "display_name": "X",
                "model_kind": "chat",
            }
        ],
    }
    path = tmp_path / "prefix.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="must start with provider prefix"):
        ModelCatalog.load_from_path(path)


def test_recommended_models_validated(tmp_path: Path) -> None:
    doc = {
        "catalog_version": 1,
        "providers": [
            {
                "id": "other",
                "display_name": "Other",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
            },
            {
                "id": "p",
                "display_name": "P",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
                "recommended_models": {"chat": "other:x"},
            },
        ],
        "models": [
            {
                "id": "other:x",
                "provider_id": "other",
                "display_name": "X",
                "model_kind": "chat",
            },
            {
                "id": "p:y",
                "provider_id": "p",
                "display_name": "Y",
                "model_kind": "chat",
            },
        ],
    }
    path = tmp_path / "rec.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="belongs to provider"):
        ModelCatalog.load_from_path(path)


def test_recommended_models_wrong_kind(tmp_path: Path) -> None:
    doc = {
        "catalog_version": 1,
        "providers": [
            {
                "id": "p",
                "display_name": "P",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
                "recommended_models": {"chat": "p:tts1"},
            }
        ],
        "models": [
            {
                "id": "p:tts1",
                "provider_id": "p",
                "display_name": "T",
                "model_kind": "tts",
            },
        ],
    }
    path = tmp_path / "rec2.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="model_kind"):
        ModelCatalog.load_from_path(path)


def test_suggested_defaults_empty_and_populated(tmp_path: Path) -> None:
    doc = {
        "catalog_version": 1,
        "providers": [
            {
                "id": "p",
                "display_name": "P",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
                "recommended_models": {"chat": "p:one"},
            }
        ],
        "models": [
            {
                "id": "p:one",
                "provider_id": "p",
                "display_name": "One",
                "model_kind": "chat",
            },
        ],
    }
    path = tmp_path / "sd.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    cat = ModelCatalog.load_from_path(path)
    assert cat.suggested_defaults("missing") == {}
    assert cat.suggested_defaults("p") == {"chat": "p:one"}


def test_replacement_id_must_exist(tmp_path: Path) -> None:
    doc = {
        "catalog_version": 1,
        "providers": [
            {
                "id": "p",
                "display_name": "P",
                "hosting": "cloud",
                "credential_env_keys": [],
                "metadata_updated_at": "2026-01-01",
            }
        ],
        "models": [
            {
                "id": "p:old",
                "provider_id": "p",
                "display_name": "Old",
                "model_kind": "chat",
                "deprecated_since": "2026-01-01",
                "replacement_id": "p:missing",
            },
        ],
    }
    path = tmp_path / "repl.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="replacement_id"):
        ModelCatalog.load_from_path(path)
