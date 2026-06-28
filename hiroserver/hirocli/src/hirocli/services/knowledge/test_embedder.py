from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

import numpy as np
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


def test_fastembed_backend_concurrent_init_is_thread_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent first-use init must create exactly one model and never fail."""
    create_count = 0
    create_lock = threading.Lock()

    class FakeTextEmbedding:
        def __init__(self, **kwargs: Any) -> None:
            nonlocal create_count
            with create_lock:
                create_count += 1
            time.sleep(0.05)

        def embed(
            self,
            documents: list[str],
            batch_size: int = 256,
            **kwargs: Any,
        ) -> Iterable[np.ndarray]:
            del batch_size, kwargs
            for _ in documents:
                yield np.zeros(DEFAULT_VECTOR_SIZE, dtype=np.float32)

    monkeypatch.setattr("fastembed.TextEmbedding", FakeTextEmbedding)

    embedder = FastEmbedBackend(cache_dir=tmp_path / "fastembed_cache")
    errors: list[str] = []
    barrier = threading.Barrier(4)

    def run() -> None:
        barrier.wait()
        try:
            vectors = embedder.embed_texts(["concurrent ingest smoke"])
            assert len(vectors) == 1
            assert len(vectors[0]) == DEFAULT_VECTOR_SIZE
        except Exception as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert create_count == 1


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

    # No forced default: empty knowledge override + empty workspace default → resolved id is None
    # (the service builds an UnconfiguredEmbedder; here fake_resolve just records the id).
    prefs = WorkspacePreferences()
    prefs.knowledge.default_embedding_model = None
    prefs.llm.default_embedder = None
    service = create_knowledge_service(tmp_path, prefs=prefs)
    try:
        assert captured["model_id"] is None
    finally:
        import asyncio

        asyncio.run(service.close())

    # The workspace default feeds the knowledge embedder when the override is empty.
    captured.clear()
    prefs2 = WorkspacePreferences()
    prefs2.knowledge.default_embedding_model = None
    prefs2.llm.default_embedder = DEFAULT_KNOWLEDGE_EMBEDDING_MODEL
    service2 = create_knowledge_service(tmp_path, prefs=prefs2)
    try:
        assert captured["model_id"] == DEFAULT_KNOWLEDGE_EMBEDDING_MODEL
        assert isinstance(service2.embedder, FastEmbedBackend)
    finally:
        import asyncio

        asyncio.run(service2.close())


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
