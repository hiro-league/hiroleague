"""Structured FINEINFO audit logs for knowledge search, answer, and ingest.

Mirrors ``services/memory/audit_log.py``: each operation has a ``build_*_audit``
helper that produces a self-contained dict and a ``log_*`` helper that emits a
human-readable FINEINFO line plus ``audit_json=...`` for the FINEINFO sink.
"""

from __future__ import annotations

import json
from typing import Any

# Caps to keep a single FINEINFO line bounded.
_QUERY_MAX_CHARS = 1000
_ANSWER_MAX_CHARS = 4000
_HIT_TEXT_MAX_CHARS = 320


def build_search_audit(
    *,
    query: str,
    top_k: int,
    min_score: float,
    filters: dict[str, Any],
    hits: list[Any],
    elapsed_ms: int,
) -> dict[str, Any]:
    return {
        "operation": "knowledge.search",
        "elapsed_ms": max(0, int(elapsed_ms)),
        "params": {
            "query": _truncate(query, _QUERY_MAX_CHARS),
            "top_k": int(top_k),
            "min_score": _coerce_score(min_score),
            "filters": dict(filters or {}),
        },
        "results": _ranked_hits(hits),
    }


def build_answer_audit(
    *,
    query: str,
    answer: str,
    top_k: int,
    min_score: float,
    filters: dict[str, Any],
    sources: list[Any],
    model_id: str | None,
    usage: dict[str, Any] | None,
    elapsed_ms: int,
    no_results: bool,
) -> dict[str, Any]:
    return {
        "operation": "knowledge.answer",
        "elapsed_ms": max(0, int(elapsed_ms)),
        "params": {
            "query": _truncate(query, _QUERY_MAX_CHARS),
            "top_k": int(top_k),
            "min_score": _coerce_score(min_score),
            "filters": dict(filters or {}),
        },
        "model_id": model_id,
        "usage": dict(usage or {}),
        "no_results": bool(no_results),
        "answer": _truncate(answer, _ANSWER_MAX_CHARS),
        "sources": _ranked_hits(sources),
    }


def build_ingest_audit(
    *,
    job_id: str,
    status: str,
    totals: dict[str, int],
    errors: dict[str, str],
    params: dict[str, Any],
    elapsed_ms: int,
) -> dict[str, Any]:
    return {
        "operation": "knowledge.ingest",
        "elapsed_ms": max(0, int(elapsed_ms)),
        "job_id": job_id,
        "status": status,
        "totals": dict(totals or {}),
        "errors": dict(errors or {}),
        "params": _ingest_params(params),
    }


def log_knowledge_search(logger: Any, audit: dict[str, Any]) -> None:
    results = audit.get("results") or []
    elapsed_ms = audit.get("elapsed_ms", 0)
    logger.fineinfo(
        "⬇️ knowledge.search — %d hit(s) · %dms",
        len(results),
        elapsed_ms,
        audit_json=_audit_json(audit),
    )


def log_knowledge_answer(logger: Any, audit: dict[str, Any]) -> None:
    sources = audit.get("sources") or []
    elapsed_ms = audit.get("elapsed_ms", 0)
    logger.fineinfo(
        "⬇️ knowledge.answer — %s · %d source(s) · %dms",
        "no_results" if audit.get("no_results") else "answered",
        len(sources),
        elapsed_ms,
        audit_json=_audit_json(audit),
    )


def log_knowledge_ingest(logger: Any, audit: dict[str, Any]) -> None:
    totals = audit.get("totals") or {}
    elapsed_ms = audit.get("elapsed_ms", 0)
    logger.fineinfo(
        "⬆️ knowledge.ingest — job=%s · %s · files=%d · chunks=%d · %dms",
        audit.get("job_id") or "-",
        audit.get("status") or "?",
        int(totals.get("ingested") or 0),
        int(totals.get("chunks") or 0),
        elapsed_ms,
        audit_json=_audit_json(audit),
    )


def _ranked_hits(hits: list[Any]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for index, hit in enumerate(hits, start=1):
        row: dict[str, Any] = {"rank": index}
        if hit is None:
            ranked.append(row)
            continue
        document_id = _read(hit, "document_id")
        point_id = _read(hit, "point_id")
        score = _coerce_score(_read(hit, "score"))
        title = str(_read(hit, "title") or "")
        text = str(_read(hit, "text") or "")
        if document_id is not None:
            row["document_id"] = document_id
        if point_id is not None:
            row["point_id"] = point_id
        if score is not None:
            row["score"] = score
        if title:
            row["title"] = title
        if text:
            row["text"] = _truncate(text, _HIT_TEXT_MAX_CHARS)
        ranked.append(row)
    return ranked


def _ingest_params(params: dict[str, Any]) -> dict[str, Any]:
    if not params:
        return {}
    return {
        "owner_kind": params.get("owner_kind"),
        "owner_id": params.get("owner_id"),
        "category_id": params.get("category_id"),
        "subcategory_id": params.get("subcategory_id"),
        "tags": list(params.get("tags") or []),
        "file_count": len(params.get("paths") or []),
        "file_concurrency": params.get("file_concurrency"),
    }


def _read(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _coerce_score(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _truncate(text: str, max_chars: int) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3] + "..."


def _audit_json(audit: dict[str, Any]) -> str:
    return json.dumps(audit, ensure_ascii=False, default=str)
