"""Tests for workspace credential store (in-memory keyring shim)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.model_catalog import ModelCatalog, clear_model_catalog_cache


@pytest.fixture(autouse=True)
def _clear_cat() -> None:
    clear_model_catalog_cache()
    yield
    clear_model_catalog_cache()


def test_set_get_remove_api_key_round_trip(tmp_path: Path) -> None:
    secrets: dict[tuple[str, str], str] = {}
    store = CredentialStore(tmp_path, "ws-test-1", _test_secrets=secrets)
    store.set_api_key("openai", "sk-test")
    assert store.get_api_key("openai") == "sk-test"
    assert store.is_configured("openai")
    assert store.remove("openai")
    assert not store.is_configured("openai")
    assert store.get_api_key("openai") is None


def test_unknown_provider_rejected(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path, "ws-1", _test_secrets={})
    with pytest.raises(ValueError, match="Unknown catalog"):
        store.set_api_key("not_a_real_provider_xyz", "k")


def test_providers_json_round_trip(tmp_path: Path) -> None:
    secrets: dict[tuple[str, str], str] = {}
    store = CredentialStore(tmp_path, "ws-2", _test_secrets=secrets)
    store.set_api_key("openai", "k1")
    path = store.providers_file()
    assert path.exists()
    store2 = CredentialStore(tmp_path, "ws-2", _test_secrets=secrets)
    assert store2.is_configured("openai")


def test_local_endpoint_no_keyring_secret(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path, "ws-3", _test_secrets={})
    store.set_local_endpoint("ollama", "http://localhost:11434")
    assert store.is_configured("ollama")
    cred = store.get("ollama")
    assert cred is not None
    assert cred.auth_method == "local_endpoint"
    assert cred.base_url == "http://localhost:11434"


def _catalog_with_env_provider(tmp_path: Path) -> ModelCatalog:
    doc = {
        "catalog_version": 1,
        "providers": [
            {
                "id": "pa",
                "display_name": "PA",
                "hosting": "cloud",
                "credential_env_keys": ["PA_KEY"],
                "metadata_updated_at": "2026-01-01",
            },
        ],
        "models": [],
    }
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return ModelCatalog.load_from_path(p)


def test_import_detected_env_keys_imports_when_unconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cat = _catalog_with_env_provider(tmp_path)
    monkeypatch.setattr("hirocli.domain.credential_store.get_model_catalog", lambda: cat)
    monkeypatch.setenv("PA_KEY", "secret-from-env")
    secrets: dict[tuple[str, str], str] = {}
    store = CredentialStore(tmp_path, "ws-env", _test_secrets=secrets)
    n = store.import_detected_env_keys()
    assert n == 1
    assert store.is_configured("pa")
    assert store.get_api_key("pa") == "secret-from-env"


def test_import_detected_env_keys_skips_already_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cat = _catalog_with_env_provider(tmp_path)
    monkeypatch.setattr("hirocli.domain.credential_store.get_model_catalog", lambda: cat)
    monkeypatch.setenv("PA_KEY", "from-env")
    secrets: dict[tuple[str, str], str] = {}
    store = CredentialStore(tmp_path, "ws-skip", _test_secrets=secrets)
    store.set_api_key("pa", "stored-first")
    n = store.import_detected_env_keys()
    assert n == 0
    assert store.get_api_key("pa") == "stored-first"
