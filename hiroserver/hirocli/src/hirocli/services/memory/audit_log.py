"""Structured FINEINFO audit logs for mem0 search and add operations."""

from __future__ import annotations

import json
from typing import Any

# Cap turn text in add audits so a single log line cannot blow up sinks.
_ADD_CONTENT_MAX_CHARS = 4000

_MEMORY_TEXT_KEYS = ("memory", "text", "content", "data", "value")


def build_search_audit(
    *,
    query: str,
    user_id: int,
    character_id: str,
    top_k: int,
    threshold: float,
    rerank_requested: bool,
    rerank_applied: bool,
    reranker_enabled: bool,
    filters: dict[str, Any],
    results: list[dict[str, Any]],
    elapsed_ms: int,
) -> dict[str, Any]:
    return {
        "operation": "search",
        "elapsed_ms": max(0, int(elapsed_ms)),
        "params": {
            "query": query,
            "user_id": user_id,
            "character_id": character_id,
            "top_k": top_k,
            "threshold": threshold,
            "rerank_requested": rerank_requested,
            "rerank_applied": rerank_applied,
            "reranker_enabled": reranker_enabled,
            "filters": filters,
        },
        "results": _ranked_search_results(results),
    }


def build_add_audit(
    *,
    user_id: int,
    character_id: str,
    run_id: str,
    content: str,
    metadata: dict[str, Any] | None,
    stored_count: int,
    stored_items: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    usage: Any | None,
    elapsed_ms: int,
) -> dict[str, Any]:
    usage_block: dict[str, Any] | None = None
    if usage is not None:
        usage_block = {
            "provider": getattr(usage, "provider", ""),
            "model": getattr(usage, "model", ""),
            "input_tokens": getattr(usage, "input_tokens", 0),
            "output_tokens": getattr(usage, "output_tokens", 0),
            "cached_input_tokens": getattr(usage, "cached_input_tokens", 0),
            "reasoning_tokens": getattr(usage, "reasoning_tokens", 0),
            "call_count": getattr(usage, "call_count", 0),
        }
    return {
        "operation": "add",
        "elapsed_ms": max(0, int(elapsed_ms)),
        "params": {
            "user_id": user_id,
            "character_id": character_id,
            "run_id": run_id,
            "metadata": dict(metadata or {}),
            "content": _truncate(content, _ADD_CONTENT_MAX_CHARS),
        },
        "stored_count": stored_count,
        "usage": usage_block,
        "results": _ranked_add_results(stored_items),
    }


def log_memory_search(
    logger: Any,
    audit: dict[str, Any],
    *,
    user_id: int,
    character_id: str,
) -> None:
    results = audit.get("results") or []
    elapsed_ms = audit.get("elapsed_ms", 0)
    logger.fineinfo(
        "⬇️ memory.search — user=%s · character=%s · %d hit(s) · %dms",
        user_id,
        character_id or "-",
        len(results),
        elapsed_ms,
        audit_json=_audit_json(audit),
    )


def log_memory_add(
    logger: Any,
    audit: dict[str, Any],
    *,
    user_id: int,
    character_id: str,
    run_id: str,
) -> None:
    stored_count = int(audit.get("stored_count") or 0)
    elapsed_ms = audit.get("elapsed_ms", 0)
    logger.fineinfo(
        "⬆️ memory.add — user=%s · character=%s · run=%s · stored=%d · %dms",
        user_id,
        character_id or "-",
        run_id or "-",
        stored_count,
        elapsed_ms,
        audit_json=_audit_json(audit),
    )


def _ranked_search_results(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for index, item in enumerate(memories, start=1):
        row: dict[str, Any] = {"rank": index}
        if isinstance(item, dict):
            row.update(_search_score_fields(item))
            if item.get("id") is not None:
                row["id"] = item["id"]
            text = _memory_text(item)
            if text:
                row["memory"] = text
            for key in ("metadata", "hash", "created_at", "updated_at"):
                if key in item and item[key] is not None:
                    row[key] = item[key]
        else:
            row["memory"] = str(item)
        ranked.append(row)
    return ranked


def _search_score_fields(item: dict[str, Any]) -> dict[str, Any]:
    """Map mem0 search scores into audit rows.

    mem0 hybrid retrieval sets ``score`` (combined semantic + BM25 + entity, [0, 1]).
    When ``rerank=True``, the cross-encoder adds ``rerank_score`` (unbounded logits);
    the original ``score`` is kept on the dict. ``effective_score`` is what ordered the row.
    """
    hybrid = _coerce_score(item.get("score"))
    rerank = _coerce_score(item.get("rerank_score"))
    fields: dict[str, Any] = {}
    if "score" in item or hybrid is not None:
        fields["score"] = hybrid
    if rerank is not None:
        fields["rerank_score"] = rerank
    effective = rerank if rerank is not None else hybrid
    if effective is not None:
        fields["effective_score"] = effective
    return fields


def _coerce_score(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _ranked_add_results(
    items: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            ranked.append({"rank": index, "memory": str(item)})
            continue
        row: dict[str, Any] = {"rank": index}
        if item.get("id") is not None:
            row["id"] = item["id"]
        if item.get("event") is not None:
            row["event"] = item["event"]
        text = _memory_text(item)
        if text:
            row["memory"] = text
        if item.get("previous_memory") is not None:
            row["previous_memory"] = item["previous_memory"]
        ranked.append(row)
    return ranked


def _memory_text(item: dict[str, Any]) -> str:
    for key in _MEMORY_TEXT_KEYS:
        value = item.get(key)
        if value is not None and str(value).strip():
            return " ".join(str(value).split())
    return ""


def _truncate(text: str, max_chars: int) -> str:
    compact = str(text or "")
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3] + "..."


def _audit_json(audit: dict[str, Any]) -> str:
    return json.dumps(audit, ensure_ascii=False, default=str)
