"""Local (in-process) knowledge reranker registry — the non-catalog analog of the model catalog.

Cloud rerankers (Voyage / Cohere) live in ``catalog.yaml`` and resolve through the model
factory. Local cross-encoders (FlashRank / FastEmbed / sentence-transformers) are in-process
library models with no API key and no provider endpoint, so — exactly like the default
FastEmbed *embedder* — they are NOT catalog rows. They live here, keyed by a ``local:`` id, and
resolve to a LangChain ``BaseDocumentCompressor``.

Hard rule (see docs/rag-optimize.md): **no local model may download silently.** A model is
usable only after an explicit ``download()``; ``build_local_compressor`` refuses to load a model
that was never downloaded (raising ``RerankerNotDownloadedError``) so selecting an un-downloaded
model fails fast and the graph falls back to retrieval order — it never triggers a hidden fetch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger
from langchain_core.callbacks import Callbacks
from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor
from pydantic import ConfigDict, PrivateAttr

from hirocli.services.knowledge.constants import KNOWLEDGE_DIR

log = Logger.get("SVC.KNOWLEDGE.RERANK")

# Local rerankers download into a dedicated cache, separate from the embedder's fastembed_cache
# so a reranker download and an embedder download never collide.
RERANKER_CACHE_DIR = "reranker_cache"


class RerankerNotDownloadedError(RuntimeError):
    """Raised when a local reranker is selected but its weights were never downloaded."""

    def __init__(self, model_id: str) -> None:
        super().__init__(
            f"Local reranker {model_id!r} is not downloaded. "
            f"Download it first (no model is fetched silently)."
        )
        self.model_id = model_id


@dataclass(frozen=True)
class LocalRerankerSpec:
    """A local in-process reranker option (the registry analog of a catalog ModelSpec)."""

    id: str  # ``local:<slug>`` — distinct from catalog ``provider:model`` ids
    display_name: str
    backend: str  # "flashrank" | "fastembed" | "sentence_transformers"
    model_ref: str  # the name passed to the backend loader
    size_label: str
    languages: str
    multilingual: bool
    context_window: int  # max input tokens the cross-encoder accepts
    # True when the backend already emits a calibrated [0,1] score (pass-through); False when it
    # emits an unbounded cross-encoder logit (the rerank step applies a sigmoid to normalize).
    scores_calibrated: bool
    description: str = ""
    # Extra kwargs handed to the backend loader (e.g. trust_remote_code for gte).
    model_kwargs: dict[str, Any] = field(default_factory=dict)


# Curated local options. ``local:`` ids never collide with catalog ``provider:model`` ids.
LOCAL_RERANKERS: tuple[LocalRerankerSpec, ...] = (
    LocalRerankerSpec(
        id="local:ms-marco-multibert-l-12",
        display_name="MultiBERT-L-12 (FlashRank)",
        backend="flashrank",
        model_ref="ms-marco-MultiBERT-L-12",
        size_label="~150 MB",
        languages="multilingual (100+)",
        multilingual=True,
        context_window=512,
        scores_calibrated=True,
        description="Small multilingual ONNX cross-encoder (no torch). Recommended first local download.",
    ),
    LocalRerankerSpec(
        id="local:bge-reranker-base",
        display_name="BGE Reranker Base (FastEmbed)",
        backend="fastembed",
        model_ref="BAAI/bge-reranker-base",
        size_label="~1.0 GB",
        languages="multilingual",
        multilingual=True,
        context_window=512,
        scores_calibrated=False,
        description="FastEmbed ONNX (no torch). Multilingual but large.",
    ),
    LocalRerankerSpec(
        id="local:bge-reranker-v2-m3",
        display_name="BGE Reranker v2-m3 (sentence-transformers)",
        backend="sentence_transformers",
        model_ref="BAAI/bge-reranker-v2-m3",
        size_label="~2.3 GB",
        languages="excellent (100+)",
        multilingual=True,
        context_window=8192,
        scores_calibrated=False,
        description="Best local multilingual/Arabic quality. Uses torch.",
    ),
    # NOTE: Alibaba-NLP/gte-multilingual-reranker-base was evaluated and dropped — its custom
    # remote-code RoPE architecture is incompatible with the sentence-transformers CrossEncoder
    # input path (corrupted position_ids → IndexError at inference), even with trust_remote_code.
    # bge-reranker-v2-m3 covers the strong-local-multilingual need without a bespoke loader.
)

_BY_ID: dict[str, LocalRerankerSpec] = {spec.id: spec for spec in LOCAL_RERANKERS}


def list_local_rerankers() -> list[LocalRerankerSpec]:
    return list(LOCAL_RERANKERS)


def get_local_reranker(model_id: str) -> LocalRerankerSpec | None:
    return _BY_ID.get((model_id or "").strip())


def is_local_reranker(model_id: str) -> bool:
    return (model_id or "").strip() in _BY_ID


def reranker_cache_dir(workspace_path: Path) -> Path:
    return Path(workspace_path) / KNOWLEDGE_DIR / RERANKER_CACHE_DIR


def is_downloaded(spec: LocalRerankerSpec, cache_dir: Path) -> bool:
    """True when ``download`` has previously completed for this model into ``cache_dir``.

    Uses the shared download-marker scheme (see ``download_markers``) so reranker and embedder
    availability are tracked the same way.
    """
    from hirocli.services.knowledge.download_markers import is_marked

    return is_marked(cache_dir, spec.id)


def download(spec: LocalRerankerSpec, cache_dir: Path) -> None:
    """Explicitly fetch a local reranker's weights into ``cache_dir`` (blocking).

    Instantiates the backend once (which performs the download), then writes the marker. Any
    failure propagates with a logged error and leaves no marker, so the model stays "not
    downloaded".
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        if spec.backend == "flashrank":
            from flashrank import Ranker

            Ranker(model_name=spec.model_ref, cache_dir=str(cache_dir))
        elif spec.backend == "fastembed":
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            TextCrossEncoder(model_name=spec.model_ref, cache_dir=str(cache_dir))
        elif spec.backend == "sentence_transformers":
            from sentence_transformers import CrossEncoder

            CrossEncoder(
                spec.model_ref,
                cache_folder=str(cache_dir),
                device="cpu",
                **spec.model_kwargs,
            )
        else:
            raise ValueError(f"Unknown local reranker backend: {spec.backend!r}")
    except Exception:
        log.error(
            "❌ Reranker download failed — HiroServer · %s",
            spec.id,
            backend=spec.backend,
            model_ref=spec.model_ref,
            exc_info=True,
        )
        raise
    from hirocli.services.knowledge.download_markers import write_marker

    write_marker(cache_dir, spec.id, content=spec.model_ref)
    log.info(
        "✅ Reranker downloaded — HiroServer · %s",
        spec.id,
        backend=spec.backend,
        size=spec.size_label,
    )


class FastEmbedCrossEncoderReranker(BaseDocumentCompressor):
    """Tiny ``BaseDocumentCompressor`` over FastEmbed's ONNX ``TextCrossEncoder``.

    FastEmbed ships no LangChain wrapper, so this adapts it to the same compressor interface the
    cloud rerankers use — keeping the local ONNX lane (no torch) behind one contract. Scores are
    raw cross-encoder logits; normalization to [0,1] is the rerank step's job.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model_name: str
    cache_dir: str | None = None
    top_n: int = 8
    _model: Any = PrivateAttr(default=None)

    def _ensure_model(self) -> Any:
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._model = TextCrossEncoder(model_name=self.model_name, cache_dir=self.cache_dir)
        return self._model

    def compress_documents(
        self,
        documents: list[Document],
        query: str,
        callbacks: Callbacks | None = None,
    ) -> list[Document]:
        docs = list(documents)
        if not docs:
            return []
        scores = list(self._ensure_model().rerank(query, [d.page_content for d in docs]))
        ranked = sorted(zip(docs, scores), key=lambda pair: pair[1], reverse=True)[: self.top_n]
        out: list[Document] = []
        for doc, score in ranked:
            out.append(
                Document(
                    page_content=doc.page_content,
                    metadata={**doc.metadata, "relevance_score": float(score)},
                )
            )
        return out


class SentenceTransformersReranker(BaseDocumentCompressor):
    """``BaseDocumentCompressor`` over a sentence-transformers ``CrossEncoder``.

    Constructs ``CrossEncoder`` directly (instead of LangChain's ``HuggingFaceCrossEncoder``) so
    ``trust_remote_code`` is passed as the **top-level** arg — it must reach the model, tokenizer
    *and* config for custom-architecture rerankers like ``gte-multilingual-reranker-base``.
    Routing it only to the model (which the LangChain wrapper does) loads the wrong tokenizer and
    crashes with a token-id out-of-bounds error. Scores are raw logits (normalized by the rerank step).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model_name: str
    cache_dir: str | None = None
    top_n: int = 8
    device: str | None = None
    # Extra top-level CrossEncoder kwargs (e.g. {"trust_remote_code": True} for gte).
    extra_kwargs: dict[str, Any] = {}
    _model: Any = PrivateAttr(default=None)

    def _ensure_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            # ``cache_folder`` is the only supported way to set the cache root (passing cache_dir
            # via *_kwargs collides with sentence-transformers' internal handling). It emits a
            # benign upstream deprecation warning — harmless; the model loads correctly.
            self._model = CrossEncoder(
                self.model_name,
                cache_folder=self.cache_dir,
                device=self.device or None,
                **self.extra_kwargs,
            )
        return self._model

    def compress_documents(
        self,
        documents: list[Document],
        query: str,
        callbacks: Callbacks | None = None,
    ) -> list[Document]:
        docs = list(documents)
        if not docs:
            return []
        scores = self._ensure_model().predict([(query, doc.page_content) for doc in docs])
        ranked = sorted(
            zip(docs, (float(score) for score in scores)),
            key=lambda pair: pair[1],
            reverse=True,
        )[: self.top_n]
        return [
            Document(
                page_content=doc.page_content,
                metadata={**doc.metadata, "relevance_score": score},
            )
            for doc, score in ranked
        ]


def build_local_compressor(
    spec: LocalRerankerSpec,
    *,
    cache_dir: Path,
    top_n: int,
    device: str | None = None,
) -> BaseDocumentCompressor:
    """Build the LangChain compressor for a downloaded local reranker.

    Refuses (raises ``RerankerNotDownloadedError``) when the model was never downloaded, so this
    never triggers a silent fetch.
    """
    if not is_downloaded(spec, cache_dir):
        raise RerankerNotDownloadedError(spec.id)

    if spec.backend == "flashrank":
        from flashrank import Ranker
        from langchain_community.document_compressors import FlashrankRerank

        ranker = Ranker(model_name=spec.model_ref, cache_dir=str(cache_dir))
        return FlashrankRerank(client=ranker, model=spec.model_ref, top_n=top_n)

    if spec.backend == "fastembed":
        return FastEmbedCrossEncoderReranker(
            model_name=spec.model_ref,
            cache_dir=str(cache_dir),
            top_n=top_n,
        )

    if spec.backend == "sentence_transformers":
        return SentenceTransformersReranker(
            model_name=spec.model_ref,
            cache_dir=str(cache_dir),
            top_n=top_n,
            device=device,
            extra_kwargs=dict(spec.model_kwargs),
        )

    raise ValueError(f"Unknown local reranker backend: {spec.backend!r}")
