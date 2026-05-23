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


@dataclass(frozen=True)
class KnowledgeAnswerResult:
    query: str
    answer: str
    sources: list[KnowledgeSource]
    elapsed_ms: int
    model_id: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    no_results: bool = False


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
