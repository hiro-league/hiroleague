"""Local FastEmbed and catalog-backed embedding backends for knowledge vectors."""

from __future__ import annotations

import os
import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from hirocli.services.knowledge.constants import (
    DEFAULT_EMBEDDING_MODEL,
    KNOWLEDGE_VECTOR_BATCH_SIZE,
)


class EmbeddingBackend(Protocol):
    dimension: int

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one dense vector per text."""


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

    @property
    def dimension(self) -> int:
        """Vector width for the configured FastEmbed model (no weight download)."""
        if self._dimension is None:
            from fastembed import TextEmbedding

            self._dimension = int(TextEmbedding.get_embedding_size(self.model_name))
        return self._dimension

    def _ensure_model(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding

            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="The model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 now uses mean pooling.*",
                )
                self._model = TextEmbedding(
                    model_name=self.model_name,
                    cache_dir=str(self.cache_dir) if self.cache_dir is not None else None,
                    threads=min(os.cpu_count() or 1, 4),
                    lazy_load=True,
                )
        return self._model

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._ensure_model().embed(list(texts), batch_size=KNOWLEDGE_VECTOR_BATCH_SIZE)
        return [vector.astype(float).tolist() for vector in vectors]
