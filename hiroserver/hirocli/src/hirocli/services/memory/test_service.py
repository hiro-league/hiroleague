"""Tests for memory service model preference wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.model_catalog import ModelCatalog, clear_model_catalog_cache
from hirocli.domain.preferences import (
    MemoryPreferences,
    MemoryRerankerPreferences,
    MemorySearchPreferences,
    ResolvedModel,
    WorkspacePreferences,
)
from hirocli.services.memory import create_memory_service
from hirocli.services.memory.service import (
    _entity_filters,
    _log_embedding_model_change,
    _mem0_model_config,
    _merge_metadata_filters,
    _reranker_config,
)


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
            {
                "id": "google:gemini-3-flash-preview",
                "provider_id": "google",
                "display_name": "Gemini 3 Flash Preview",
                "model_kind": "chat",
            },
            {
                "id": "google:gemini-2.5-flash",
                "provider_id": "google",
                "display_name": "Gemini 2.5 Flash",
                "model_kind": "chat",
            },
        ],
    }
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    cat = ModelCatalog.load_from_path(path)
    monkeypatch.setattr("hirocli.domain.model_catalog.get_model_catalog", lambda: cat)
    monkeypatch.setattr("hirocli.domain.model_factory.get_model_catalog", lambda: cat)
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
    resolved = ResolvedModel(
        model_id="openai:gpt-test",
        temperature=0,
        max_tokens=8192,
        thinking="low",
    )
    monkeypatch.setattr("hirocli.domain.preferences.resolve_memory_llm", lambda *a, **k: resolved)
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
    assert calls["workspace_path"] == tmp_path
    assert calls["llm_model"] == "openai:gpt-test"
    assert calls["llm_tuning"] is resolved
    assert calls["embedding_model"] == "openai:text-embedding-3-small"
    assert calls["credential_store"] is store
    # Factory forwards search + reranker prefs so the service can read its defaults.
    assert isinstance(calls["search_prefs"], MemorySearchPreferences)
    assert isinstance(calls["reranker_prefs"], MemoryRerankerPreferences)


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
    """Chat models route through the langchain adapter so we have a single,
    provider-agnostic callback path for usage capture and content
    normalization. The configured API key must reach the underlying client.
    """
    _catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, "w1", _test_secrets={})
    store.set_api_key("openai", "sk-test")

    config = _mem0_model_config(
        tmp_path,
        "openai:gpt-test",
        required_kind="chat",
        credential_store=store,
    )

    assert config["provider"] == "langchain"
    model = config["config"]["model"]
    assert model._default_params["model"] == "gpt-test"
    assert model.max_tokens == 8192
    assert model.openai_api_key.get_secret_value() == "sk-test"


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
    assert model._default_params["max_completion_tokens"] == 8192
    assert "max_tokens" not in model._default_params


def test_mem0_model_config_pins_thinking_low_for_gemini_3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini 3's default ``thinking_level="high"`` consumes the output budget
    and truncates mem0's extraction JSON. The memory service must pin thinking
    low so the response budget covers the actual JSON.
    """
    _catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, "w1", _test_secrets={})
    store.set_api_key("google", "gk-test")

    config = _mem0_model_config(
        tmp_path,
        "google:gemini-3-flash-preview",
        required_kind="chat",
        credential_store=store,
    )

    assert config["provider"] == "langchain"
    model = config["config"]["model"]
    assert model.thinking_level == "low"
    assert model.max_output_tokens == 8192


def test_mem0_model_config_disables_thinking_budget_for_gemini_2_5(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _catalog(tmp_path, monkeypatch)
    store = CredentialStore(tmp_path, "w1", _test_secrets={})
    store.set_api_key("google", "gk-test")

    config = _mem0_model_config(
        tmp_path,
        "google:gemini-2.5-flash",
        required_kind="chat",
        credential_store=store,
    )

    model = config["config"]["model"]
    assert model.thinking_budget == 1024
    assert model.max_output_tokens == 8192


def test_entity_filters_use_native_user_and_agent_ids() -> None:
    """``character_id`` rides on mem0's ``agent_id`` slot so retrieval uses
    native entity filtering instead of metadata gymnastics.
    """
    assert _entity_filters(7, "aria") == {"user_id": "7", "agent_id": "aria"}
    # Without a character we still scope by user — used by the global memory list.
    assert _entity_filters(7, None) == {"user_id": "7"}


def test_merge_metadata_filters_combines_entity_and_metadata_keys() -> None:
    base = {"user_id": "7", "agent_id": "aria"}
    merged = _merge_metadata_filters(base, {"source": "conversation", "channel_id": 42})
    assert merged == {
        "user_id": "7",
        "agent_id": "aria",
        "source": "conversation",
        "channel_id": 42,
    }
    # Metadata filters can override entity scoping when the caller asks explicitly.
    overridden = _merge_metadata_filters(base, {"run_id": "session-9"})
    assert overridden == {"user_id": "7", "agent_id": "aria", "run_id": "session-9"}


def test_reranker_config_disabled_by_default() -> None:
    """No reranker block means mem0 won't try to import sentence-transformers."""
    assert _reranker_config(MemoryRerankerPreferences()) is None


def test_reranker_config_uses_sentence_transformer_provider() -> None:
    prefs = MemoryRerankerPreferences(
        enabled=True,
        model="cross-encoder/ms-marco-MiniLM-L-6-v2",
        device="cpu",
        batch_size=16,
    )
    cfg = _reranker_config(prefs)
    assert cfg == {
        "provider": "sentence_transformer",
        "config": {
            "model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
            "device": "cpu",
            "batch_size": 16,
        },
    }


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
