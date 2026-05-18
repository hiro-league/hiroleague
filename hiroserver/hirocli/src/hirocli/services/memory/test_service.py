"""Tests for memory service model preference wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.model_catalog import ModelCatalog, clear_model_catalog_cache
from hirocli.domain.preferences import MemoryPreferences, WorkspacePreferences
from hirocli.services.memory import create_memory_service
from hirocli.services.memory.service import _log_embedding_model_change, _mem0_model_config


@pytest.fixture(autouse=True)
def _clear_cat() -> None:
    clear_model_catalog_cache()
    yield
    clear_model_catalog_cache()


def _catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModelCatalog:
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
                "display_name": "GPT Test",
                "model_kind": "chat",
            },
            {
                "id": "openai:gpt-5.4",
                "provider_id": "openai",
                "display_name": "GPT 5.4",
                "model_kind": "chat",
            },
            {
                "id": "openai:text-embedding-3-small",
                "provider_id": "openai",
                "display_name": "Text Embedding 3 Small",
                "model_kind": "embedding",
            },
        ],
    }
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    cat = ModelCatalog.load_from_path(path)
    monkeypatch.setattr("hirocli.domain.model_catalog.get_model_catalog", lambda: cat)
    monkeypatch.setattr("hirocli.domain.credential_store.get_model_catalog", lambda: cat)
    return cat


def test_create_memory_service_disabled_when_models_are_null(tmp_path: Path) -> None:
    prefs = WorkspacePreferences(
        memory=MemoryPreferences(
            enabled=True,
            default_llm="openai:gpt-test",
            default_embedding_model=None,
        )
    )
    assert prefs.memory.enabled is False
    assert create_memory_service(tmp_path, prefs) is None


def test_create_memory_service_passes_memory_model_preferences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    class FakeMemoryService:
        def __init__(self, **kwargs: Any) -> None:
            calls.update(kwargs)

    monkeypatch.setattr("hirocli.services.memory.service.Mem0MemoryService", FakeMemoryService)
    store = object()
    prefs = WorkspacePreferences(
        memory=MemoryPreferences(
            enabled=True,
            default_llm="openai:gpt-test",
            default_embedding_model="openai:text-embedding-3-small",
        )
    )

    service = create_memory_service(tmp_path, prefs, credential_store=store)

    assert isinstance(service, FakeMemoryService)
    assert calls == {
        "workspace_path": tmp_path,
        "llm_model": "openai:gpt-test",
        "embedding_model": "openai:text-embedding-3-small",
        "credential_store": store,
    }


def test_mem0_model_config_requires_embedding_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, "w1", _test_secrets={})
    store.set_api_key("openai", "sk-test")

    with pytest.raises(ValueError, match="wrong kind"):
        _mem0_model_config(
            tmp_path,
            "openai:gpt-test",
            required_kind="embedding",
            credential_store=store,
        )


def test_mem0_model_config_uses_configured_provider_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, "w1", _test_secrets={})
    store.set_api_key("openai", "sk-test")

    config = _mem0_model_config(
        tmp_path,
        "openai:gpt-test",
        required_kind="chat",
        credential_store=store,
    )

    assert config == {
        "provider": "openai",
        "config": {"model": "gpt-test", "api_key": "sk-test"},
    }


def test_mem0_model_config_uses_langchain_for_openai_gpt5(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, "w1", _test_secrets={})
    store.set_api_key("openai", "sk-test")

    config = _mem0_model_config(
        tmp_path,
        "openai:gpt-5.4",
        required_kind="chat",
        credential_store=store,
    )

    assert config["provider"] == "langchain"
    model = config["config"]["model"]
    assert model._default_params["model"] == "gpt-5.4"
    assert model._default_params["max_completion_tokens"] == 2000
    assert "max_tokens" not in model._default_params


def test_embedding_model_change_logs_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory_dir = tmp_path / "memory"
    qdrant_path = memory_dir / "qdrant"
    qdrant_path.mkdir(parents=True)
    (qdrant_path / "data.bin").write_text("vectors", encoding="utf-8")
    (memory_dir / "embedding_model.txt").write_text("openai:old", encoding="utf-8")
    calls: list[dict[str, Any]] = []

    class FakeLog:
        def error(self, message: str, **kwargs: Any) -> None:
            calls.append({"message": message, **kwargs})

    monkeypatch.setattr("hirocli.services.memory.service.log", FakeLog())

    _log_embedding_model_change(tmp_path, "openai:text-embedding-3-small")

    assert calls == [
        {
            "message": "Memory embedding model changed; existing Qdrant vectors may be incompatible",
            "previous": "openai:old",
            "current": "openai:text-embedding-3-small",
            "qdrant_path": str(qdrant_path),
        }
    ]
