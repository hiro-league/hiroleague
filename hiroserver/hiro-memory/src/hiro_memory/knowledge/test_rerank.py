"""Reranking hits over a handed-in compressor, and the relevance normalization."""

from __future__ import annotations

import math

import pytest
from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor

from hiro_memory.knowledge.agent.helpers import minmax_relevances
from hiro_memory.knowledge.rerank import _normalize, rerank_hits
from hiro_memory.testing import knowledge_hit


def _hit(i: int, text: str, score: float):
    return knowledge_hit(point_id=f"p{i}", text=text, score=score)


class _StubReranker(BaseDocumentCompressor):
    """Reverses the candidate order and assigns descending logits (2.0, 1.0, …)."""

    def compress_documents(self, documents, query, callbacks=None):  # type: ignore[override]
        out = []
        for rank, doc in enumerate(reversed(list(documents))):
            out.append(
                Document(
                    page_content=doc.page_content,
                    metadata={**doc.metadata, "relevance_score": 2.0 - rank},
                )
            )
        return out


# --- normalization ----------------------------------------------------------


def test_normalize_calibrated_passthrough_and_clamp() -> None:
    assert _normalize(0.42, calibrated=True) == 0.42
    assert _normalize(1.5, calibrated=True) == 1.0
    assert _normalize(-0.2, calibrated=True) == 0.0


def test_normalize_logit_uses_sigmoid() -> None:
    assert _normalize(0.0, calibrated=False) == pytest.approx(0.5)
    assert _normalize(2.0, calibrated=False) == pytest.approx(1 / (1 + math.exp(-2.0)))


def test_minmax_relevances() -> None:
    assert minmax_relevances([0.1, 0.5, 0.9]) == [0.0, 0.5, 1.0]
    # degenerate (all equal) → all 1.0; empty → empty
    assert minmax_relevances([0.3, 0.3]) == [1.0, 1.0]
    assert minmax_relevances([]) == []


# --- rerank_hits -------------------------------------------------------------


def test_rerank_hits_reorders_trims_and_normalizes() -> None:
    hits = [_hit(0, "a", 0.9), _hit(1, "b", 0.5), _hit(2, "c", 0.1)]
    out = rerank_hits(_StubReranker(), "q", hits, scores_calibrated=False, top_n=2)
    # reversed order, trimmed to top_n=2
    assert [h.point_id for h in out] == ["p2", "p1"]
    # raw logit recorded; relevance is the sigmoid of it
    assert out[0].rerank_score == 2.0
    assert out[0].relevance == pytest.approx(1 / (1 + math.exp(-2.0)))


def test_rerank_hits_empty_returns_empty() -> None:
    assert rerank_hits(_StubReranker(), "q", [], scores_calibrated=True, top_n=5) == []
