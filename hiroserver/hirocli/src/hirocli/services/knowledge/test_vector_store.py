from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.services.knowledge.constants import KNOWLEDGE_VECTOR_BATCH_SIZE
from hirocli.services.knowledge.vector_store import KnowledgeVectorStore


class FakeEmbedder:
    dimension = 8

    def embed_texts(self, texts):
        return [[0.1] * self.dimension for _ in texts]


def _fake_sparse(count: int):
    """One non-empty BM25-style sparse vector (indices, values) per chunk."""
    return [([0, index + 1], [1.0, 1.0]) for index in range(count)]


def test_upsert_document_vectors_writes_flat_payload_without_nested_metadata(
    tmp_path: Path,
) -> None:
    store = KnowledgeVectorStore(tmp_path / "qdrant", FakeEmbedder())
    try:
        store.upsert_document_vectors(
            "00000000-0000-4000-8000-000000000001",
            tmp_path / "note.md",
            "Title",
            "text/markdown",
            [{"text": "chunk-0", "heading_path": "# Title"}],
            [[0.1] * FakeEmbedder.dimension],
            _fake_sparse(1),
            {"owner_kind": "system", "owner_id": "0"},
            ["tag"],
            "2026-01-01T00:00:00+00:00",
        )
        chunks, _ = store.scroll_document_chunks(
            "00000000-0000-4000-8000-000000000001", limit=10
        )
        assert chunks
        for chunk in chunks:
            assert "metadata" not in chunk
            assert chunk["text"] == "chunk-0"
            assert chunk["tags"] == ["tag"]
            assert chunk["document_id"] == "00000000-0000-4000-8000-000000000001"
    finally:
        store.close()


def test_upsert_document_vectors_batches_qdrant_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = KnowledgeVectorStore(tmp_path / "qdrant", FakeEmbedder())
    try:
        client = store.qdrant
        batch_sizes: list[int] = []
        original_upsert = client.upsert

        def tracking_upsert(*args, **kwargs):
            points = kwargs.get("points") or (args[1] if len(args) > 1 else None)
            if points is not None:
                batch_sizes.append(len(points))
            return original_upsert(*args, **kwargs)

        monkeypatch.setattr(client, "upsert", tracking_upsert)
        chunk_count = KNOWLEDGE_VECTOR_BATCH_SIZE + 5
        chunks = [{"text": f"chunk-{index}", "heading_path": None} for index in range(chunk_count)]
        vectors = [[0.1] * FakeEmbedder.dimension for _ in chunks]
        store.upsert_document_vectors(
            "00000000-0000-4000-8000-000000000001",
            tmp_path / "note.md",
            "Title",
            "text/markdown",
            chunks,
            vectors,
            _fake_sparse(chunk_count),
            {"owner_kind": "system", "owner_id": "0"},
            ["tag"],
            "2026-01-01T00:00:00+00:00",
        )
        assert batch_sizes == [KNOWLEDGE_VECTOR_BATCH_SIZE, 5]
    finally:
        store.close()


def test_reload_embedder_revalidates_existing_collection(tmp_path: Path) -> None:
    """A late embedder swap must not silently land on a mismatched collection."""

    class BiggerEmbedder:
        dimension = 16

        def embed_texts(self, texts):
            return [[0.0] * self.dimension for _ in texts]

    store = KnowledgeVectorStore(tmp_path / "qdrant", FakeEmbedder())
    try:
        store.upsert_document_vectors(
            "00000000-0000-4000-8000-000000000001",
            tmp_path / "note.md",
            "Title",
            "text/markdown",
            [{"text": "chunk-0", "heading_path": None}],
            [[0.1] * FakeEmbedder.dimension],
            _fake_sparse(1),
            {"owner_kind": "system", "owner_id": "0"},
            [],
            "2026-01-01T00:00:00+00:00",
        )
        with pytest.raises(RuntimeError, match="vector size"):
            store.reload_embedder(BiggerEmbedder())
    finally:
        store.close()


def test_search_hybrid_dense_and_fused_paths(tmp_path: Path) -> None:
    """Both the RRF-fused path and the dense-only fallback return the stored chunks."""
    store = KnowledgeVectorStore(tmp_path / "qdrant", FakeEmbedder())
    try:
        chunks = [{"text": f"chunk-{index}", "heading_path": None} for index in range(3)]
        store.upsert_document_vectors(
            "00000000-0000-4000-8000-000000000001",
            tmp_path / "note.md",
            "Title",
            "text/markdown",
            chunks,
            [[0.1] * FakeEmbedder.dimension for _ in chunks],
            _fake_sparse(len(chunks)),
            {"owner_kind": "system", "owner_id": "0"},
            [],
            "2026-01-01T00:00:00+00:00",
        )
        dense_query = [0.1] * FakeEmbedder.dimension
        # Hybrid: dense + BM25 prefetch fused with RRF.
        fused = store.search_hybrid(dense_query, ([0, 1], [1.0, 1.0]), top_k=5, hybrid=True)
        assert fused
        # Dense-only path.
        dense_only = store.search_hybrid(dense_query, None, top_k=5, hybrid=False)
        assert dense_only
        # Hybrid requested but empty sparse → falls back to dense, still returns hits.
        empty_sparse = store.search_hybrid(dense_query, ([], []), top_k=5, hybrid=True)
        assert empty_sparse
    finally:
        store.close()


def test_search_hybrid_explain_exposes_per_branch_scores(tmp_path: Path) -> None:
    """explain=True attaches per-branch cosine/BM25 scores; the default path leaves them None."""
    store = KnowledgeVectorStore(tmp_path / "qdrant", FakeEmbedder())
    try:
        chunks = [{"text": f"chunk-{index}", "heading_path": None} for index in range(3)]
        store.upsert_document_vectors(
            "00000000-0000-4000-8000-000000000001",
            tmp_path / "note.md",
            "Title",
            "text/markdown",
            chunks,
            [[0.1] * FakeEmbedder.dimension for _ in chunks],
            _fake_sparse(len(chunks)),
            {"owner_kind": "system", "owner_id": "0"},
            [],
            "2026-01-01T00:00:00+00:00",
        )
        dense_query = [0.1] * FakeEmbedder.dimension
        sparse_query = ([0, 1], [1.0, 1.0])

        # Default fused path: no per-branch diagnostics.
        plain = store.search_hybrid(dense_query, sparse_query, top_k=5, hybrid=True, explain=False)
        assert plain
        assert all(hit.dense_score is None and hit.sparse_score is None for hit in plain)

        # Explain path: per-branch scores populated (presence = which branch matched).
        explained = store.search_hybrid(dense_query, sparse_query, top_k=5, hybrid=True, explain=True)
        assert explained
        assert any(hit.dense_score is not None for hit in explained)
        assert any(hit.sparse_score is not None for hit in explained)
    finally:
        store.close()
