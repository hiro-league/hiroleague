"""Rerank retrieved hits with a LangChain ``BaseDocumentCompressor`` the owner picked (cloud or local).

``rerank_hits`` runs the compressor over retrieved hits, reorders + trims to ``top_n``, and records both the native
``rerank_score`` and a normalized ``relevance`` in [0,1] (pass-through for calibrated API scores; sigmoid for
unbounded cross-encoder logits). Which compressor, and whether its scores are calibrated, is the owner's call.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

from langchain_core.documents import Document

if TYPE_CHECKING:
    from langchain_core.documents.compressor import BaseDocumentCompressor

    from hiro_memory.knowledge.models import KnowledgeSearchHit


def _normalize(score: float, *, calibrated: bool) -> float:
    if calibrated:
        return max(0.0, min(1.0, float(score)))
    # Sigmoid maps an unbounded cross-encoder logit into (0, 1).
    return 1.0 / (1.0 + math.exp(-float(score)))


def rerank_hits(
    compressor: "BaseDocumentCompressor",
    query: str,
    hits: list["KnowledgeSearchHit"],
    *,
    scores_calibrated: bool,
    top_n: int,
) -> list["KnowledgeSearchHit"]:
    """Reorder + trim hits by the reranker, stamping ``rerank_score`` + normalized ``relevance``.

    Synchronous (model inference / network) — callers should run it off the event loop.
    """
    if not hits:
        return []
    # Carry the original index in metadata so we can map the reordered docs back to hits.
    docs = [Document(page_content=hit.text, metadata={"_idx": i}) for i, hit in enumerate(hits)]
    compressed = compressor.compress_documents(docs, query)
    out: list[KnowledgeSearchHit] = []
    for doc in compressed:
        idx = doc.metadata.get("_idx")
        if not isinstance(idx, int) or not (0 <= idx < len(hits)):
            continue
        raw = doc.metadata.get("relevance_score")
        rerank_score = float(raw) if raw is not None else None
        relevance = (
            _normalize(rerank_score, calibrated=scores_calibrated)
            if rerank_score is not None
            else None
        )
        out.append(replace(hits[idx], rerank_score=rerank_score, relevance=relevance))
    return out[:top_n]
