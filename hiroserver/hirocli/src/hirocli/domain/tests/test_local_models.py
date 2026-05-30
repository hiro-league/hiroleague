"""Tests for the local-models browse adapter (domain/local_models.py)."""

from __future__ import annotations

from pathlib import Path

from hirocli.domain.local_models import LocalModelRow, list_local_model_rows


def test_rerank_rows_shape_and_overlay(tmp_path: Path) -> None:
    rows = list_local_model_rows(tmp_path, model_kind="rerank")
    assert rows and all(isinstance(r, LocalModelRow) for r in rows)
    multibert = next(r for r in rows if r.id == "local:ms-marco-multibert-l-12")
    assert multibert.provider_id == "local"  # single synthetic local provider
    assert multibert.backend == "flashrank"  # backend is a tag, not the provider
    assert multibert.model_kind == "rerank"
    assert multibert.hosting == "local"
    assert multibert.source == "local"
    assert multibert.free is True
    assert multibert.context_window == 512
    assert "flashrank" in multibert.features
    # Fresh workspace cache → nothing downloaded yet.
    assert multibert.downloaded is False


def test_embedding_row_present(tmp_path: Path) -> None:
    rows = list_local_model_rows(tmp_path, model_kind="embedding")
    assert len(rows) == 1
    emb = rows[0]
    assert emb.model_kind == "embedding"
    assert emb.provider_id == "local"
    assert emb.backend == "fastembed"
    assert emb.hosting == "local"
    assert emb.free is True
    assert "ingest" in emb.manage_hint.lower()  # auto-download hint, not the reranker hint
    assert emb.downloaded is False  # fresh tmp cache (no marker)


def test_kind_filter(tmp_path: Path) -> None:
    # Unknown kind yields nothing; rerank/embedding each yield their own rows.
    assert list_local_model_rows(tmp_path, model_kind="chat") == []
    assert all(r.model_kind == "rerank" for r in list_local_model_rows(tmp_path, model_kind="rerank"))
    # No filter returns rerankers + the embedder.
    all_rows = list_local_model_rows(tmp_path)
    kinds = {r.model_kind for r in all_rows}
    assert kinds == {"rerank", "embedding"}
    assert len(all_rows) >= 4
