"""Workspace-local knowledge (RAG) settings (``prefs.knowledge``). Split out of ``models.py``.

Qdrant chunking / retrieval / reranking / answering knobs. The shared Graphiti graph engine lives
in the top-level ``prefs.graph`` (see ``models_graph``), not here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .defaults import (
    DEFAULT_KNOWLEDGE_ANSWERING_PROMPT,
    DEFAULT_KNOWLEDGE_REWRITE_PROMPT,
    DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID,
    pref_field,
)

DEFAULT_KNOWLEDGE_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class KnowledgeChunkingMarkdownPreferences(BaseModel):
    respect_headings: bool = Field(
        default=True,
        title="Respect markdown headings",
        description="Split chunks at markdown headings when ingesting documents.",
    )


class KnowledgeChunkingPreferences(BaseModel):
    chunk_size: int = Field(
        default=1200,
        ge=200,
        le=8000,
        title="Chunk size",
        description="Target size per chunk at document ingest (characters).",
    )
    chunk_overlap: int = Field(
        default=150,
        ge=0,
        le=2000,
        title="Chunk overlap",
        description="Overlap between consecutive chunks. Must stay smaller than chunk size.",
    )
    embed_structural_context: bool = pref_field(
        # Demo seed for the admin "show advanced" toggle: a low-level ingest knob most users
        # never touch. Remove/adjust `advanced` here (and on any other field) to taste.
        advanced=True,
        default=True,
        title="Embed structural context",
        description=(
            "Prefix each chunk's embedded text with its document title and heading path so every chunk "
            "— including continuation pieces — carries its section context. Applies to new ingests; "
            "changing this requires re-ingesting existing documents."
        ),
    )
    markdown: KnowledgeChunkingMarkdownPreferences = Field(default_factory=KnowledgeChunkingMarkdownPreferences)

    @model_validator(mode="after")
    def _overlap_less_than_size(self) -> "KnowledgeChunkingPreferences":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("knowledge.chunking.chunk_overlap must be smaller than chunk_size")
        return self


class KnowledgeRerankerPreferences(BaseModel):
    """Cross-encoder reranker over retrieved candidates (precision step).

    Prefs-only, default off. ``model_id`` is a catalog ``provider:model`` (cloud: Voyage /
    Cohere) OR a local-registry id (FlashRank / FastEmbed / sentence-transformers). It is
    resolved by ``resolve_reranker`` to a LangChain ``BaseDocumentCompressor`` — the same way
    ``default_embedding_model`` is resolved by the embedder. Rerankers are dimensionless, so a
    swap is a hot config change (no re-ingest). ``device`` / ``batch_size`` apply to the local
    torch lane only and are ignored by cloud models. ``model_id`` null = fall back to the
    workspace default reranker (``llm.default_reranker``); if that is empty too, no reranker
    (retrieval order used as-is) even when ``enabled`` is true.
    """

    enabled: bool = Field(default=False, title="Enable reranking")
    model_id: str | None = pref_field(
        model_kind="rerank",
        default=None,
        title="Reranker model",
        description=(
            "Cross-encoder used to reorder retrieved candidates. Empty = fall back to the "
            "default reranker (General → Models). Local models must be downloaded first."
        ),
    )
    top_n: int = Field(default=8, ge=1, le=100, title="Rerank results (top N)", description="Final returned results if using rerank (top N).")
    device: str | None = None
    batch_size: int = Field(default=32, ge=1, le=512)


class KnowledgeRetrievalPreferences(BaseModel):
    top_k: int = Field(default=20, ge=1, le=100, title="Search/fused results (top K)", description="Fused results from hybrid search or direct results from dense only search (after applying minimum score).")
    min_score: float = pref_field(step=0.05, default=0.0, ge=0.0, le=1.0, title="Minimum score (Dense only)", description="Applies only to dense (Vector search) branch.")
    # Hybrid retrieval: fuse the dense vector with a BM25 sparse vector via Qdrant RRF.
    # Sparse vectors are always stored at ingest, so this is a pure query-time toggle
    # (flipping it needs no re-ingest). When enabled, ``min_score`` applies as the cosine
    # threshold on the dense branch; the BM25 branch is rank-fused (its scores are not 0-1).
    hybrid: bool = Field(default=True, title="Hybrid retrieval (dense + BM25, RRF fusion)")
    # The BM25 sparse model is a fixed constant (services.knowledge.constants.DEFAULT_SPARSE_MODEL),
    # not a preference: the Qdrant collection is hardwired to BM25's IDF scoring and switching would
    # need a full re-ingest, so it was removed from the editable preference surface.
    # Candidates pulled per branch before fusion; should be >= top_k so RRF has overlap.
    prefetch_limit: int = Field(default=40, ge=1, le=500, title="Candidates per branch", description="Results to return for dense (Vector) or sparse (BM25) separately, before RRF fusion (Hybrid Only).")
    reranker: KnowledgeRerankerPreferences = Field(default_factory=KnowledgeRerankerPreferences)


class KnowledgeAnsweringPreferences(BaseModel):
    model: str | None = pref_field(
        model_kind="chat", default=None, title="Knowledge answering model"
    )
    # Base answer-generation system prompt. Editable; blank falls back to the relaxed default
    # (partial answers allowed, no bare "I don't know" when any part is supported). The citation
    # and language clauses are appended at runtime from the fields below.
    prompt: str = Field(default=DEFAULT_KNOWLEDGE_ANSWERING_PROMPT, title="Answering prompt")
    cite_sources: bool = Field(default=True, title="Cite sources")
    language_policy: Literal["match_query", "prefer_english", "prefer_arabic"] = Field(
        default="match_query", title="Language policy"
    )


class KnowledgeRewritePreferences(BaseModel):
    # Optional LLM query rewrite for the Ask tab: normalize + extract literal keywords before
    # retrieval. Reuses the resolved answering model. ``default_on`` seeds the Ask-tab toggle.
    prompt: str = Field(default=DEFAULT_KNOWLEDGE_REWRITE_PROMPT, title="Query Rewrite Prompt")
    default_on: bool = Field(default=False, title="Enable Query Rewrite on Ask Tab")


class KnowledgePreferences(BaseModel):
    # Knowledge embedder OVERRIDE. Empty = inherit the workspace default (llm.default_embedder),
    # resolved by ``resolve_knowledge_embedder_model``. Locked (UI badge + pre-save write-guard)
    # once the knowledge collection has points — embedders are dimension-bound, so changing this
    # after indexing would orphan the stored vectors. Field name kept (historical) to preserve the
    # existing lock + value for already-indexed workspaces without a migration.
    default_embedding_model: str | None = pref_field(
        model_kind="embedding",
        default=None,
        title="Knowledge embedder",
        description="Knowledge embedder. Empty inherits the workspace default (General → Models).",
    )
    default_tuning_profile: str = pref_field(
        tuning_profile_ref=True,
        default=DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID,
        title="Knowledge answering model profile",
    )
    chunking: KnowledgeChunkingPreferences = Field(default_factory=KnowledgeChunkingPreferences)
    retrieval: KnowledgeRetrievalPreferences = Field(default_factory=KnowledgeRetrievalPreferences)
    answering: KnowledgeAnsweringPreferences = Field(default_factory=KnowledgeAnsweringPreferences)
    rewrite: KnowledgeRewritePreferences = Field(default_factory=KnowledgeRewritePreferences)
