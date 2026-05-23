from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hirocli.domain.preferences import DEFAULT_KNOWLEDGE_EMBEDDING_MODEL, WorkspacePreferences
from hirocli.services.knowledge import create_knowledge_service
from hirocli.services.knowledge.embedder import CatalogEmbeddingsBackend, resolve_knowledge_embedder
from hirocli.services.knowledge.constants import DEFAULT_EMBEDDING_MODEL, DEFAULT_VECTOR_SIZE
from hirocli.services.knowledge.embedding_backends import FastEmbedBackend


def test_resolve_knowledge_embedder_uses_fastembed_for_default(tmp_path: Path) -> None:
    embedder = resolve_knowledge_embedder(tmp_path, DEFAULT_KNOWLEDGE_EMBEDDING_MODEL)
    assert isinstance(embedder, FastEmbedBackend)
    assert embedder.model_name == DEFAULT_EMBEDDING_MODEL
    assert embedder.dimension == DEFAULT_VECTOR_SIZE


def test_fastembed_backend_dimension_matches_non_default_model(tmp_path: Path) -> None:
    model_name = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    embedder = resolve_knowledge_embedder(tmp_path, model_name)
    assert isinstance(embedder, FastEmbedBackend)
    assert embedder.model_name == model_name
    assert embedder.dimension == 768


def test_create_knowledge_service_reads_default_embedding_preference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def fake_resolve(workspace_path: Path, model_id: str, *, credential_store=None):
        captured["model_id"] = model_id
        return FastEmbedBackend(cache_dir=workspace_path / "knowledge" / "fastembed_cache")

    monkeypatch.setattr(
        "hirocli.services.knowledge.embedder.resolve_knowledge_embedder",
        fake_resolve,
    )

    prefs = WorkspacePreferences()
    prefs.knowledge.default_embedding_model = None
    service = create_knowledge_service(tmp_path, prefs=prefs)
    try:
        assert captured["model_id"] == DEFAULT_KNOWLEDGE_EMBEDDING_MODEL
        assert isinstance(service.embedder, FastEmbedBackend)
    finally:
        import asyncio

        asyncio.run(service.close())


def test_resolve_knowledge_embedder_uses_catalog_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "hirocli.services.knowledge.embedder._is_catalog_embedding_model",
        lambda model_id: model_id == "openai:text-embedding-3-small",
    )
    monkeypatch.setattr(
        "hirocli.domain.model_factory.create_embedding_model",
        lambda model_id, **kwargs: SimpleNamespace(
            embed_documents=lambda docs: [[0.1] * 1536 for _ in docs],
        ),
    )

    embedder = resolve_knowledge_embedder(tmp_path, "openai:text-embedding-3-small")
    assert isinstance(embedder, CatalogEmbeddingsBackend)
    assert embedder.model_name == "openai:text-embedding-3-small"
    assert embedder.dimension == 1536
    assert len(embedder.embed_texts(["hello"])[0]) == 1536
