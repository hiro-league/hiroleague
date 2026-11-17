"""Ledger previews of retrieved passages: the top results as short ``[ref] relevance Title :: snippet`` rows."""

from __future__ import annotations

from typing import Any


def relevance_of(item: Any) -> float | None:
    """Best calibrated score for a hit/source: ``relevance`` ([0,1], reranker-aware) → ``rerank_score``
    → raw backend ``score``. The raw ``score`` (cosine/RRF) is uncalibrated and not the final
    ranking signal once a reranker runs, so prefer ``relevance`` for previews."""
    for attr in ("relevance", "rerank_score", "score"):
        value = getattr(item, attr, None)
        if isinstance(value, (int, float)):
            return float(value)
    return None


# Retrieval previews get a larger budget than the 280-char default so a few result snippets fit —
# enough to eyeball whether retrieval actually returned relevant content.
KNOWLEDGE_PREVIEW_MAX = 600


def knowledge_results_rows(items: list[Any], *, limit: int = 3, snippet_len: int = 130) -> str:
    """``[ref] rel Title :: snippet`` rows for the top results, so the actual retrieved content (not
    just counts/scores) is visible. Score is the calibrated, reranker-aware ``relevance``."""
    rows: list[str] = []
    for index, item in enumerate(items[:limit], start=1):
        ref = getattr(item, "ref", None) or index
        title = " ".join(str(getattr(item, "title", "") or "").split())[:50] or "<untitled>"
        relevance = relevance_of(item)
        rel_text = f" {relevance:.2f}" if relevance is not None else ""
        # Episode event date — only set on build_context sources (graph legs); upstream
        # hits carry no valid_at, so this renders nothing for vector_search/rerank rows.
        valid_at = getattr(item, "valid_at", None)
        date = f" — {valid_at}" if valid_at else ""
        snippet = " ".join(str(getattr(item, "text", "") or "").split())[:snippet_len]
        rows.append(f"[{ref}]{rel_text} {title}{date} :: {snippet}")
    return " | ".join(rows)
