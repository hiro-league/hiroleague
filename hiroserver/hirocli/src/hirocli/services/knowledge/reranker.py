"""Resolve a knowledge reranker compressor (cloud catalog or local registry).

``resolve_reranker`` mirrors ``resolve_knowledge_embedder``: a local-registry id resolves to a
local in-process compressor; anything else is a catalog ``provider:model`` resolved (cloud) via
the model factory. Both return a LangChain ``BaseDocumentCompressor`` behind one interface.

The memory library's ``hiro_memory.knowledge.rerank.rerank_hits`` runs the compressor over
retrieved hits.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hirocli.services.knowledge.reranker_registry import (
    build_local_compressor,
    get_local_reranker,
    reranker_cache_dir,
)

if TYPE_CHECKING:
    from langchain_core.documents.compressor import BaseDocumentCompressor

    from hirocli.domain.credential_store import CredentialStore


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
