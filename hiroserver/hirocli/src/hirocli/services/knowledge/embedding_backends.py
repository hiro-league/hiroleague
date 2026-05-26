"""Local FastEmbed and catalog-backed embedding backends for knowledge vectors."""

from __future__ import annotations

import os
import threading
import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from hiro_commons.log import Logger

from hirocli.services.knowledge.constants import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_SPARSE_MODEL,
    KNOWLEDGE_VECTOR_BATCH_SIZE,
)

log = Logger.get("SVC.KNOWLEDGE.EMBED")

# A sparse vector as (indices, values) — the shape Qdrant's SparseVector expects.
SparseVectorData = tuple[list[int], list[float]]


class EmbeddingBackend(Protocol):
    dimension: int

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one dense vector per text."""


class SparseEmbeddingBackend(Protocol):
    model_name: str

    def embed_documents(self, texts: Sequence[str]) -> list[SparseVectorData]:
        """Return one sparse vector (indices, values) per document text."""

    def embed_query(self, text: str) -> SparseVectorData:
        """Return the sparse vector for a single query."""


class FastEmbedBackend:
    """Lazy FastEmbed wrapper so model weights download only on first real use."""

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        *,
        cache_dir: Path | None = None,
    ) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._model: Any | None = None
        self._dimension: int | None = None
        # FastEmbed lazy_load is not thread-safe during first model init (tokenizer race).
        self._init_lock = threading.Lock()

    @property
    def dimension(self) -> int:
        """Vector width for the configured FastEmbed model (no weight download)."""
        if self._dimension is None:
            from fastembed import TextEmbedding

            self._dimension = int(TextEmbedding.get_embedding_size(self.model_name))
        return self._dimension

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._init_lock:
            if self._model is not None:
                return self._model
            from fastembed import TextEmbedding

            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="The model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 now uses mean pooling.*",
                )
                # Eager load inside the lock; lazy_load has a tokenizer init race under concurrency.
                self._model = TextEmbedding(
                    model_name=self.model_name,
                    cache_dir=str(self.cache_dir) if self.cache_dir is not None else None,
                    threads=min(os.cpu_count() or 1, 4),
                    lazy_load=False,
                )
        return self._model

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._ensure_model().embed(list(texts), batch_size=KNOWLEDGE_VECTOR_BATCH_SIZE)
        return [vector.astype(float).tolist() for vector in vectors]


def _sparse_pair(embedding: Any) -> SparseVectorData:
    """Convert a FastEmbed SparseEmbedding (numpy indices/values) to plain lists."""
    return ([int(i) for i in embedding.indices], [float(v) for v in embedding.values])


class SparseFastEmbedBackend:
    """Lazy FastEmbed sparse (BM25) wrapper for hybrid retrieval.

    BM25 weighting differs index- vs query-side, so documents go through ``embed`` and
    queries through ``query_embed``. The model is not neural — it downloads only ~10 MB
    of per-language stopwords (incl. Arabic) on first use, into the shared FastEmbed cache.
    Independent of the dense embedder, so it is unaffected by dense-model swaps.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_SPARSE_MODEL,
        *,
        cache_dir: Path | None = None,
    ) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._model: Any | None = None
        self._init_lock = threading.Lock()

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._init_lock:
            if self._model is not None:
                return self._model
            from fastembed import SparseTextEmbedding

            try:
                # Eager load inside the lock (mirrors the dense backend's tokenizer-race guard).
                self._model = SparseTextEmbedding(
                    model_name=self.model_name,
                    cache_dir=str(self.cache_dir) if self.cache_dir is not None else None,
                )
            except Exception:
                # Log the model identity here — the ingest-level handler only knows the document.
                log.error(
                    "❌ Sparse embedder load failed — HiroServer · %s",
                    self.model_name,
                    exc_info=True,
                )
                raise
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[SparseVectorData]:
        if not texts:
            return []
        embeddings = self._ensure_model().embed(
            list(texts), batch_size=KNOWLEDGE_VECTOR_BATCH_SIZE
        )
        return [_sparse_pair(e) for e in embeddings]

    def embed_query(self, text: str) -> SparseVectorData:
        embeddings = list(self._ensure_model().query_embed(text))
        if not embeddings:
            return ([], [])
        return _sparse_pair(embeddings[0])
