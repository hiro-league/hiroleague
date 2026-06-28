"""Resolve knowledge embedding backends from workspace preferences."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.embeddings import Embeddings

from hiro_commons.log import Logger

from hirocli.domain.preferences import DEFAULT_KNOWLEDGE_EMBEDDING_MODEL
from hirocli.services.knowledge.constants import (
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

log = Logger.get("SVC.KNOWLEDGE.EMBED")


def _log_embed_http_failure(exc: Exception, model_id: str) -> None:
    """Post-mortem for cloud-embedding HTTP failures: log the FAILED request's header sizes.

    Added for the eval-run ``431 request_headers_too_large`` investigation: the repro harness
    (test_embedder_431_repro.py) showed the client stack keeps headers flat (~600B) under the
    eval's exact concurrency, so the next real 431 must carry its own evidence. openai's
    ``APIStatusError.response`` is the ``httpx.Response`` whose ``.request`` holds the exact
    headers that were on the wire — names + per-header SIZES only (values redacted: the
    Authorization key must never reach the logs). Best-effort: never masks the original error."""
    response = getattr(exc, "response", None)
    request = getattr(response, "request", None)
    if request is None:
        return
    try:
        headers = list(request.headers.items())
        per_header = dict(
            sorted(((k, len(v)) for k, v in headers), key=lambda kv: -kv[1])
        )
        total = sum(len(k) + len(v) + 4 for k, v in headers)  # +4 ≈ ": " + CRLF per line
        log.error(
            "❌ knowledge.embed — embeddings HTTP %s · model=%s · header_total=%dB · per-header(B)=%s",
            getattr(response, "status_code", "?"),
            model_id,
            total,
            per_header,
        )
    except Exception:
        log.warning(
            "⚠️ knowledge.embed — could not introspect failed embed request", exc_info=True
        )


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
        # try/except added for the 431 investigation: surface the failed request's actual
        # header sizes (see _log_embed_http_failure) before the error propagates unchanged.
        try:
            return self._embeddings.embed_documents(list(texts))
        except Exception as exc:
            _log_embed_http_failure(exc, self.model_id)
            raise


class UnconfiguredEmbedder:
    """Placeholder embedder for when no model is configured (default + override both empty).

    Embedding is mandatory and there is NO forced default, so resolution returns this instead of
    silently picking a model. It lets the service be constructed (browsing/listing still works) but
    fails fast with a clear message the moment any embed/dimension is actually needed (ingest or
    query) — i.e. indexing is blocked until the user chooses an embedder.
    """

    model_name = ""

    @property
    def dimension(self) -> int:
        raise RuntimeError(
            "No embedder configured. Choose one in Preferences → General → Default models "
            "(or set a Knowledge/Graph embedder) before indexing or searching."
        )

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        # Reuse the dimension guard's message — same root cause (nothing to embed with).
        _ = self.dimension
        return []


def resolve_knowledge_embedder(
    workspace_path: Path,
    model_id: str | None,
    *,
    credential_store: CredentialStore | None = None,
) -> EmbeddingBackend:
    """Build the active knowledge embedder from a resolved model id.

    No forced default: an empty ``model_id`` yields an ``UnconfiguredEmbedder`` (raises on use)
    rather than silently falling back to a built-in model.
    """
    resolved = (model_id or "").strip()
    if not resolved:
        return UnconfiguredEmbedder()

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

    # Local FastEmbed lane: sentence-transformers/* ids (the local-embedder registry uses these).
    if resolved.startswith("sentence-transformers/"):
        return FastEmbedBackend(
            model_name=resolved,
            cache_dir=workspace_path / KNOWLEDGE_DIR / "fastembed_cache",
        )

    raise ValueError(
        f"Unknown embedder model {resolved!r} — not a catalog embedding model nor a local "
        f"sentence-transformers model."
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


def is_default_embedder_cached(workspace_path: Path) -> bool:
    """Is the default FastEmbed embedder downloaded in this workspace?

    Marker-based, same as rerankers (see ``download_markers``) — the FastEmbed backend writes a
    marker after its first successful load. The embedder auto-downloads on first ingest, so this
    flips to True once any knowledge ingest/query has run on this install.
    """
    from hirocli.services.knowledge.download_markers import is_marked

    cache_dir = Path(workspace_path) / KNOWLEDGE_DIR / "fastembed_cache"
    return is_marked(cache_dir, DEFAULT_KNOWLEDGE_EMBEDDING_MODEL)
