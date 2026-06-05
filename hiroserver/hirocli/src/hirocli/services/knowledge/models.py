"""Knowledge service data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LoadedKnowledgeDocument:
    title: str
    mime: str
    chunks: list[dict[str, str | None]]


@dataclass(frozen=True)
class KnowledgeDocumentRow:
    id: str
    source_uri: str
    source_type: str
    mime: str
    ext: str
    owner_kind: str
    owner_id: str
    category_id: int | None
    subcategory_id: int | None
    title: str
    # content_hash / chunk_count are NULL while a document is parsing/embedding/failed;
    # only populated once status flips to 'ready'.
    content_hash: str | None
    size_bytes: int
    chunk_count: int | None
    status: str
    error: str | None
    ingested_at: str | None
    updated_at: str
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScannedFile:
    path: str
    relative_path: str
    ext: str
    size_bytes: int
    supported: bool
    already_ingested: bool
    disabled_reason: str | None = None


@dataclass(frozen=True)
class ScanFolderResult:
    root: str
    files: list[ScannedFile]


@dataclass(frozen=True)
class KnowledgeJobResult:
    job_id: str
    status: str
    totals: dict[str, int]
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeJobRow:
    id: str
    created_at: str
    finished_at: str | None
    status: str
    totals: dict[str, int]
    errors: dict[str, str]
    params: dict[str, Any]


@dataclass(frozen=True)
class KnowledgeListJobsResult:
    jobs: list[KnowledgeJobRow]


@dataclass(frozen=True)
class KnowledgeSearchHit:
    document_id: str
    point_id: str
    score: float
    ord: int
    text: str
    heading_path: str | None
    title: str
    source_uri: str
    owner_kind: str
    owner_id: str
    category_id: int | None
    subcategory_id: int | None
    tags: list[str]
    # Explain mode (opt-in) diagnostics. None/empty on the default fused path.
    # dense_score = cosine, sparse_score = BM25 weight; presence indicates which branch matched.
    dense_score: float | None = None
    sparse_score: float | None = None
    matched_terms: list[str] = field(default_factory=list)
    # Reranker output (set by the rerank node when a reranker is active; None otherwise).
    # rerank_score = the reranker's native score (API [0,1] or cross-encoder logit — NOT
    # comparable across backends). relevance = that score normalized to [0,1] (sigmoid for
    # logits, pass-through for calibrated API scores) — the field consumers should use.
    rerank_score: float | None = None
    relevance: float | None = None


@dataclass(frozen=True)
class KnowledgeSearchResult:
    query: str
    hits: list[KnowledgeSearchHit]


@dataclass(frozen=True)
class KnowledgeSource:
    ref: int
    document_id: str
    point_id: str
    title: str
    heading_path: str | None
    source_uri: str
    score: float
    text: str
    owner_kind: str
    owner_id: str
    category_id: int | None
    subcategory_id: int | None
    tags: list[str]
    # Explain mode (opt-in) diagnostics; see KnowledgeSearchHit.
    dense_score: float | None = None
    sparse_score: float | None = None
    matched_terms: list[str] = field(default_factory=list)
    # Unified score contract — emitted whether or not a reranker ran (see KnowledgeSearchHit).
    # relevance is always populated in [0,1]; score_source tags its provenance so chat-side
    # fusion knows whether it is a calibrated reranker score or a within-set retrieval rank.
    rerank_score: float | None = None
    relevance: float | None = None
    score_source: str = "rrf"
    # Episode event date (``valid_at``, YYYY-MM-DD) of the supporting chunk, stamped by the
    # build_context node on the graph legs (graphiti/mix). Lets the answer model resolve a
    # passage's relative dates ("today") to an absolute date. None on the flat leg / no graph.
    valid_at: str | None = None


@dataclass(frozen=True)
class KnowledgeAnswerResult:
    query: str
    answer: str
    sources: list[KnowledgeSource]
    elapsed_ms: int
    model_id: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    no_results: bool = False
    run_id: str | None = None
    # Optional query rewrite (opt-in). rewritten_query is None when rewrite was off or skipped.
    rewritten_query: str | None = None
    keywords: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class KnowledgeAnswerComparison:
    """L3 — side-by-side flat-vs-graph result from ``KnowledgeService.compare``.

    Both legs ran against the same query / filters / tuning — only ``use_graph``
    toggled. ``elapsed_ms`` is the wall-clock for both legs (they run concurrently
    via ``asyncio.gather``); each leg's own ``elapsed_ms`` reflects its own time.
    """

    query: str
    flat: KnowledgeAnswerResult   # use_graph=False
    graph: KnowledgeAnswerResult  # use_graph=True
    elapsed_ms: int

    @property
    def sources_delta(self) -> int:
        """``graph - flat`` in source count — a quick "did the graph help" signal."""
        return len(self.graph.sources) - len(self.flat.sources)

    @property
    def both_no_results(self) -> bool:
        return self.flat.no_results and self.graph.no_results


@dataclass(frozen=True)
class KnowledgeListDocumentsResult:
    documents: list[KnowledgeDocumentRow]
    total: int


@dataclass(frozen=True)
class KnowledgeDocumentDetailResult:
    document: KnowledgeDocumentRow | None
    chunks: list[dict[str, Any]]
    # Opaque Qdrant scroll cursor (JSON) for the next chunk page; null when exhausted.
    chunk_next_offset: str | None = None
