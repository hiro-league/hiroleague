"""Ledger previews of retrieved passages."""

from __future__ import annotations

from types import SimpleNamespace

from hiro_memory.knowledge.previews import KNOWLEDGE_PREVIEW_MAX, knowledge_results_rows, relevance_of


def test_relevance_of_prefers_relevance_then_rerank_then_score() -> None:
    assert relevance_of(SimpleNamespace(relevance=0.9, rerank_score=0.5, score=0.1)) == 0.9
    assert relevance_of(SimpleNamespace(rerank_score=0.5, score=0.1)) == 0.5
    assert relevance_of(SimpleNamespace(score=0.1)) == 0.1
    assert relevance_of(SimpleNamespace()) is None


def test_knowledge_results_rows_builds_preview_rows() -> None:
    items = [
        SimpleNamespace(ref=1, title="Doc One", text="snippet one", relevance=0.88),
        SimpleNamespace(ref=2, title="Doc Two", text="snippet two", score=0.5),
    ]

    rows = knowledge_results_rows(items)

    assert "[1] 0.88 Doc One :: snippet one" in rows
    assert "[2] 0.50 Doc Two :: snippet two" in rows


def test_knowledge_results_rows_respects_limit() -> None:
    items = [
        SimpleNamespace(ref=i, title=f"Doc {i}", text=f"text {i}", relevance=0.5)
        for i in range(1, 6)
    ]

    rows = knowledge_results_rows(items, limit=2)

    assert "Doc 1" in rows
    assert "Doc 2" in rows
    assert "Doc 3" not in rows


def test_knowledge_preview_max_constant() -> None:
    assert KNOWLEDGE_PREVIEW_MAX == 600
