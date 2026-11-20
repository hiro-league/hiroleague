"""The knowledge settings the engine reads: how ingest chunks a file, and what the retrieval graph reads. Their values
live with the owner (the core's preferences, EvalHiro's run snapshot); the classes live here so both hand the engine the same shape.

The models, the embedders and the reranker are not settings: the owner picks them and hands them in
(``agent.config.KnowledgeGraphConfig``).
"""

from __future__ import annotations

from importlib import resources
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from hiro_memory.knowledge.constants import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE
from hiro_memory.settings import KnowledgeGraphTemporalDefault


def _load_prompt(name: str) -> str:
    """The text of the bundled default prompt ``prompts/<name>.md``; a missing file fails at import."""
    try:
        return resources.files(__package__).joinpath("prompts", f"{name}.md").read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise RuntimeError(f"Missing or unreadable default prompt file: {name}.md") from exc


# System prompt for the optional query-rewrite step; the rewrite node falls back to it when the owner's prompt is
# blank. It spells out the output shape (not left to the schema alone) because some providers, e.g. DeepSeek
# thinking mode, fall back to JSON-mode structured output that never sees the pydantic field descriptions.
DEFAULT_KNOWLEDGE_REWRITE_PROMPT = _load_prompt("knowledge_rewrite")

# System prompt for the answer step; the answer node falls back to it when the owner's prompt is blank. It allows
# PARTIAL answers and forbids a bare "I don't know" when any part is supported (the empty-context case never reaches
# it: ``no_results`` skips the model). The citation and language clauses are appended at run time.
DEFAULT_KNOWLEDGE_ANSWERING_PROMPT = _load_prompt("knowledge_answering")


class KnowledgeChunkingMarkdownSettings(BaseModel):
    respect_headings: bool = True


class KnowledgeChunkingSettings(BaseModel):
    """How a file is cut into chunks at ingest (``index.KnowledgeIndex.ingest_file``)."""

    chunk_size: int = Field(default=DEFAULT_CHUNK_SIZE, ge=200, le=8000)
    chunk_overlap: int = Field(default=DEFAULT_CHUNK_OVERLAP, ge=0, le=2000)
    # Prefix each chunk's embedded text with its document title and heading path.
    embed_structural_context: bool = True
    markdown: KnowledgeChunkingMarkdownSettings = Field(default_factory=KnowledgeChunkingMarkdownSettings)

    @model_validator(mode="after")
    def _overlap_less_than_size(self) -> "KnowledgeChunkingSettings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class KnowledgeRerankSettings(BaseModel):
    """The rerank step over retrieved candidates. Which reranker runs is the owner's pick (handed in)."""

    enabled: bool = False
    top_n: int = Field(default=8, ge=1, le=100)


class KnowledgeRetrievalSettings(BaseModel):
    top_k: int = Field(default=20, ge=1, le=100)
    # Cosine threshold on the dense branch only (BM25 scores are not 0-1).
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    # Fuse the dense vector with a BM25 sparse vector (Qdrant RRF). Sparse vectors are always stored at ingest,
    # so this is a query-time toggle.
    hybrid: bool = True
    # Candidates pulled per branch before fusion; should be >= top_k so RRF has overlap.
    prefetch_limit: int = Field(default=40, ge=1, le=500)
    reranker: KnowledgeRerankSettings = Field(default_factory=KnowledgeRerankSettings)


class KnowledgeAnsweringSettings(BaseModel):
    # Base answer instruction; blank falls back to DEFAULT_KNOWLEDGE_ANSWERING_PROMPT.
    prompt: str = DEFAULT_KNOWLEDGE_ANSWERING_PROMPT
    cite_sources: bool = True
    language_policy: Literal["match_query", "prefer_english", "prefer_arabic"] = "match_query"


class KnowledgeRewriteSettings(BaseModel):
    # Blank falls back to DEFAULT_KNOWLEDGE_REWRITE_PROMPT.
    prompt: str = DEFAULT_KNOWLEDGE_REWRITE_PROMPT


class KnowledgeSettings(BaseModel):
    """Everything the knowledge retrieval/answer graph reads from settings, for one build."""

    retrieval: KnowledgeRetrievalSettings = Field(default_factory=KnowledgeRetrievalSettings)
    answering: KnowledgeAnsweringSettings = Field(default_factory=KnowledgeAnsweringSettings)
    rewrite: KnowledgeRewriteSettings = Field(default_factory=KnowledgeRewriteSettings)
    # The graph leg's default time window when a query names none: facts true now, or all with their window.
    graph_temporal_default: KnowledgeGraphTemporalDefault = "all"
