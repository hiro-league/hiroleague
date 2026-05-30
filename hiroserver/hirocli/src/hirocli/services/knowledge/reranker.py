"""Resolve a knowledge reranker compressor (cloud catalog or local registry) and rerank hits.

``resolve_reranker`` mirrors ``resolve_knowledge_embedder``: a local-registry id resolves to a
local in-process compressor; anything else is a catalog ``provider:model`` resolved (cloud) via
the model factory. Both return a LangChain ``BaseDocumentCompressor`` behind one interface.

``rerank_hits`` runs the compressor over retrieved hits, reorders + trims to ``top_n``, and
records both the native ``rerank_score`` and a normalized ``relevance`` in [0,1] (pass-through
for calibrated API scores; sigmoid for unbounded cross-encoder logits).
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.documents import Document

from hirocli.services.knowledge.reranker_registry import (
    build_local_compressor,
    get_local_reranker,
    reranker_cache_dir,
)

if TYPE_CHECKING:
    from langchain_core.documents.compressor import BaseDocumentCompressor

    from hirocli.domain.credential_store import CredentialStore
    from hirocli.services.knowledge.models import KnowledgeSearchHit


def resolve_reranker(
    model_id: str,
    *,
    workspace_path: Path,
    workspace_id: str | None = None,
    top_n: int = 8,
    device: str | None = None,
    credential_store: "CredentialStore | None" = None,
) -> tuple["BaseDocumentCompressor", bool]:
    """Return ``(compressor, scores_calibrated)`` for the active reranker.

    ``scores_calibrated`` tells ``rerank_hits`` whether the backend already emits [0,1] scores
    (pass-through) or raw logits (sigmoid). Local registry is checked first; otherwise the id is
    a cloud catalog model. Raises if the id is unknown / unconfigured / not downloaded.
    """
    spec = get_local_reranker(model_id)
    if spec is not None:
        compressor = build_local_compressor(
            spec,
            cache_dir=reranker_cache_dir(workspace_path),
            top_n=top_n,
            device=device,
        )
        return compressor, spec.scores_calibrated

    from hirocli.domain.model_factory import create_reranker

    compressor = create_reranker(
        model_id,
        workspace_path=workspace_path,
        workspace_id=workspace_id,
        top_n=top_n,
        credential_store=credential_store,
    )
    # Cohere / Voyage return a normalized relevance_score in [0, 1].
    return compressor, True


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
