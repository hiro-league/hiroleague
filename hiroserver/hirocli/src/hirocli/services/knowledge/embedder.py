"""Resolve knowledge embedding backends from workspace preferences."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.embeddings import Embeddings

from hirocli.domain.preferences import DEFAULT_KNOWLEDGE_EMBEDDING_MODEL
from hirocli.services.knowledge.constants import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_SPARSE_MODEL,
    KNOWLEDGE_DIR,
)
from hirocli.services.knowledge.embedding_backends import (
    EmbeddingBackend,
    FastEmbedBackend,
    SparseFastEmbedBackend,
)

if TYPE_CHECKING:
    from hirocli.domain.credential_store import CredentialStore


class CatalogEmbeddingsBackend:
    """LangChain Embeddings wrapped as a knowledge ``EmbeddingBackend``."""

    def __init__(
        self,
        embeddings: Embeddings,
        *,
        model_id: str,
        dimension: int,
    ) -> None:
        self.model_id = model_id
        self.model_name = model_id
        self._embeddings = embeddings
        self.dimension = dimension

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embeddings.embed_documents(list(texts))


def resolve_knowledge_embedder(
    workspace_path: Path,
    model_id: str,
    *,
    credential_store: CredentialStore | None = None,
) -> EmbeddingBackend:
    """Build the active knowledge embedder from a resolved model id."""
    resolved = (model_id or DEFAULT_KNOWLEDGE_EMBEDDING_MODEL).strip()
    if not resolved:
        resolved = DEFAULT_KNOWLEDGE_EMBEDDING_MODEL

    if _is_catalog_embedding_model(resolved):
        from hirocli.domain.model_factory import (
            catalog_embedding_dimensions,
            create_embedding_model,
        )

        embeddings = create_embedding_model(
            resolved,
            workspace_path=workspace_path,
            credential_store=credential_store,
        )
        return CatalogEmbeddingsBackend(
            embeddings,
            model_id=resolved,
            dimension=catalog_embedding_dimensions(resolved),
        )

    fastembed_name = (
        resolved if resolved.startswith("sentence-transformers/") else DEFAULT_EMBEDDING_MODEL
    )
    return FastEmbedBackend(
        model_name=fastembed_name,
        cache_dir=workspace_path / KNOWLEDGE_DIR / "fastembed_cache",
    )


def resolve_knowledge_sparse_embedder(
    workspace_path: Path,
    sparse_model: str = DEFAULT_SPARSE_MODEL,
) -> SparseFastEmbedBackend:
    """Build the BM25 sparse backend for hybrid retrieval.

    Local and independent of the dense embedder (so dense-model swaps don't touch it).
    Shares the FastEmbed cache dir with the dense backend.
    """
    model = (sparse_model or DEFAULT_SPARSE_MODEL).strip() or DEFAULT_SPARSE_MODEL
    return SparseFastEmbedBackend(
        model_name=model,
        cache_dir=workspace_path / KNOWLEDGE_DIR / "fastembed_cache",
    )


def _is_catalog_embedding_model(model_id: str) -> bool:
    if ":" not in model_id:
        return False
    from hirocli.domain.model_catalog import get_model_catalog

    spec = get_model_catalog().get_model(model_id)
    return spec is not None and spec.supports_kind("embedding")
