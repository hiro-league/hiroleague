"""Shared graph helpers extracted from ``base.py``.

Both ``ChatAgentGraph`` and ``KnowledgeAgentGraph`` need these small, pure utilities
(message-content normalization, LLM-usage payloads, retrieval previews). They live here
so ``KnowledgeAgentGraph`` can import them without depending on the chat graph classes.
"""

from __future__ import annotations

import math
from typing import Any

from langchain_core.messages import AIMessage

from .events import make_event


def normalize_reply_content(content: Any) -> str:
    """Convert LangChain/provider message content into Hiro's plain-text body."""
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            parts.append(str(block))
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
            continue
        cv = block.get("content")
        if isinstance(cv, str):
            parts.append(cv)
    return "\n".join(p for p in parts if p)


def relevance_of(item: Any) -> float | None:
    """Best calibrated score for a hit/source: ``relevance`` ([0,1], reranker-aware) → ``rerank_score``
    → raw backend ``score``. The raw ``score`` (cosine/RRF) is uncalibrated and not the final
    ranking signal once a reranker runs, so prefer ``relevance`` for previews."""
    for attr in ("relevance", "rerank_score", "score"):
        value = getattr(item, attr, None)
        if isinstance(value, (int, float)):
            return float(value)
    return None


# Retrieval previews get a larger budget than the 280-char default so a few result snippets fit —
# enough to eyeball whether retrieval actually returned relevant content.
KNOWLEDGE_PREVIEW_MAX = 600


def knowledge_results_rows(items: list[Any], *, limit: int = 3, snippet_len: int = 130) -> str:
    """``[ref] rel Title :: snippet`` rows for the top results, so the actual retrieved content (not
    just counts/scores) is visible. Score is the calibrated, reranker-aware ``relevance``."""
    rows: list[str] = []
    for index, item in enumerate(items[:limit], start=1):
        ref = getattr(item, "ref", None) or index
        title = " ".join(str(getattr(item, "title", "") or "").split())[:50] or "<untitled>"
        relevance = relevance_of(item)
        rel_text = f" {relevance:.2f}" if relevance is not None else ""
        # Episode event date — only set on build_context sources (graph legs); upstream
        # hits carry no valid_at, so this renders nothing for vector_search/rerank rows.
        valid_at = getattr(item, "valid_at", None)
        date = f" — {valid_at}" if valid_at else ""
        snippet = " ".join(str(getattr(item, "text", "") or "").split())[:snippet_len]
        rows.append(f"[{ref}]{rel_text} {title}{date} :: {snippet}")
    return " | ".join(rows)


def llm_usage_payload(
    message: AIMessage,
    *,
    inbound_id: str,
    chat_channel_id: int,
    model_id: str,
    estimated_input_tokens: int,
) -> dict[str, Any]:
    usage = usage_from_metadata(message.usage_metadata or {})
    payload: dict[str, Any] = {
        "inbound_id": inbound_id,
        "chat_channel_id": chat_channel_id,
        "model_id": model_id,
        "usage_available": bool(usage),
    }
    if usage:
        payload.update(usage)
    else:
        payload["estimated_input_tokens"] = estimated_input_tokens
    return payload


def usage_from_metadata(raw: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = _int_token(raw.get(key))
        if value is not None:
            out[key] = value

    input_details = raw.get("input_token_details")
    if isinstance(input_details, dict):
        cached = _int_token(input_details.get("cache_read"))
        if cached is not None:
            out["cached_input_tokens"] = cached

    output_details = raw.get("output_token_details")
    if isinstance(output_details, dict):
        reasoning = _int_token(output_details.get("reasoning"))
        if reasoning is not None:
            out["reasoning_tokens"] = reasoning

    return out


def _int_token(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def estimate_text_tokens(text: str) -> int:
    stripped = str(text or "")
    if not stripped:
        return 0
    return max(1, math.ceil(len(stripped) / 4))


def emit(writer: Any, name: str, payload: dict[str, Any]) -> None:
    """Push a domain event onto the custom stream (consumed by AgentManager)."""
    writer(make_event(name, payload))
