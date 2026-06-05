"""Row, hit, and filter conversion helpers for knowledge storage."""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from typing import Any

from qdrant_client import models as qm

from hirocli.services.knowledge.constants import DEFAULT_FILE_CONCURRENCY
from hirocli.services.knowledge.embedding_backends import EmbeddingBackend, FastEmbedBackend
from hirocli.services.knowledge.models import (
    KnowledgeDocumentRow,
    KnowledgeJobRow,
    KnowledgeSearchHit,
    KnowledgeSource,
)


def utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def document_from_row(row: sqlite3.Row, *, tags: list[str] | None = None) -> KnowledgeDocumentRow:
    return KnowledgeDocumentRow(
        id=row["id"],
        source_uri=row["source_uri"],
        source_type=row["source_type"],
        mime=row["mime"],
        ext=row["ext"],
        owner_kind=row["owner_kind"],
        owner_id=row["owner_id"],
        category_id=row["category_id"],
        subcategory_id=row["subcategory_id"],
        title=row["title"],
        content_hash=row["content_hash"],
        size_bytes=row["size_bytes"],
        chunk_count=row["chunk_count"],
        status=row["status"],
        error=row["error"],
        ingested_at=row["ingested_at"],
        updated_at=row["updated_at"],
        tags=list(tags or []),
    )


def job_from_row(row: sqlite3.Row) -> KnowledgeJobRow:
    return KnowledgeJobRow(
        id=row["id"],
        created_at=row["created_at"],
        finished_at=row["finished_at"],
        status=row["status"],
        totals=json.loads(row["totals_json"] or "{}"),
        errors=json.loads(row["errors_json"] or "{}"),
        params=json.loads(row["params_json"] or "{}"),
    )


def hit_from_payload(
    payload: dict[str, Any],
    *,
    point_id: str,
    score: float,
    dense_score: float | None = None,
    sparse_score: float | None = None,
) -> KnowledgeSearchHit:
    return KnowledgeSearchHit(
        document_id=str(payload.get("document_id", "")),
        point_id=point_id,
        score=score,
        ord=int(payload.get("ord") or 0),
        text=str(payload.get("text") or ""),
        heading_path=payload.get("heading_path"),
        title=str(payload.get("title") or ""),
        source_uri=str(payload.get("source_uri") or ""),
        owner_kind=str(payload.get("owner_kind") or ""),
        owner_id=str(payload.get("owner_id") or ""),
        category_id=optional_int(payload.get("category_id")),
        subcategory_id=optional_int(payload.get("subcategory_id")),
        tags=list(payload.get("tags") or []),
        dense_score=dense_score,
        sparse_score=sparse_score,
    )


def source_from_hit(
    ref: int,
    hit: KnowledgeSearchHit,
    *,
    matched_terms: list[str] | None = None,
    relevance: float | None = None,
    score_source: str = "rrf",
    valid_at: str | None = None,
) -> KnowledgeSource:
    return KnowledgeSource(
        ref=ref,
        document_id=hit.document_id,
        point_id=hit.point_id,
        title=hit.title,
        heading_path=hit.heading_path,
        source_uri=hit.source_uri,
        score=hit.score,
        text=hit.text,
        owner_kind=hit.owner_kind,
        owner_id=hit.owner_id,
        category_id=hit.category_id,
        subcategory_id=hit.subcategory_id,
        tags=hit.tags,
        dense_score=hit.dense_score,
        sparse_score=hit.sparse_score,
        matched_terms=list(matched_terms or []),
        rerank_score=hit.rerank_score,
        # relevance falls back to the hit's own (set by the rerank node) when the caller
        # does not override; score_source is decided by the caller (reranker vs rrf/cosine).
        relevance=relevance if relevance is not None else hit.relevance,
        score_source=score_source,
        valid_at=valid_at,
    )


def document_filter(document_id: str) -> qm.Filter:
    return qm.Filter(
        must=[
            qm.FieldCondition(
                key="document_id",
                match=qm.MatchValue(value=str(document_id)),
            )
        ]
    )


def optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def default_file_concurrency_for_embedder(embedder: EmbeddingBackend) -> int:
    """Resolve ingest file parallelism from the active embedding backend."""
    if isinstance(embedder, FastEmbedBackend):
        return max(1, min(os.cpu_count() or 1, 4))
    return 8


def bounded_file_concurrency(value: Any, *, fallback: int | None = None) -> int:
    resolved_fallback = fallback if fallback is not None else DEFAULT_FILE_CONCURRENCY
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = resolved_fallback
    return max(1, min(parsed, 64))
