"""Shared graph helpers extracted from ``base.py``.

Both ``ChatAgentGraph`` and ``KnowledgeAgentGraph`` need these small, pure utilities
(message-content normalization, LLM-usage payloads, retrieval previews). They live here
so ``KnowledgeAgentGraph`` can import them without depending on the chat graph classes.
"""

from __future__ import annotations

import json
import math
from typing import Any

from hiro_memory.replies import usage_from_metadata
from langchain_core.messages import AIMessage

from .events import make_event

IDENTITY_KEYS = ("inbound_id", "chat_channel_id", "character_id")
IDENTITY_PEER_KEYS = ("inbound_id", "chat_channel_id")

# Bounded strings for admin message metadata (separate from ledger previews).
AGENT_TOOL_ARGS_MAX = 2000
AGENT_TOOL_RESULT_MAX = 4000

_MEMORY_TEXT_KEYS = ("memory", "text", "content", "data", "value")


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


def estimate_text_tokens(text: str) -> int:
    stripped = str(text or "")
    if not stripped:
        return 0
    return max(1, math.ceil(len(stripped) / 4))


def emit(writer: Any, name: str, payload: dict[str, Any]) -> None:
    """Push a domain event onto the custom stream (consumed by AgentManager)."""
    writer(make_event(name, payload))


def event_identity_from_state(state: dict[str, Any]) -> dict[str, Any]:
    """Standard event-payload identity fields (``inbound_id``/``chat_channel_id``/``character_id``)
    pulled from graph state or ``Send`` sub-state.

    Distinct from :func:`hiro_memory.ledger.identity.identity_from_state`, which
    resolves the broader ledger-row identity (``run_id``/``device_id``/``user_id``/``branch_index``
    from envelope + config + ``current_run`` fallback). The two return different shapes; keep the
    names disambiguated — a bare ``identity_from_state`` import is otherwise easy to confuse.
    """
    return {
        "inbound_id": state.get("inbound_id", ""),
        "chat_channel_id": state.get("chat_channel_id", 0),
        "character_id": state.get("character_id", ""),
    }


# Back-compat alias — prefer ``event_identity_from_state`` to avoid colliding with
# ``ledger.identity.identity_from_state``.
identity_from_state = event_identity_from_state


def emit_for(
    writer: Any,
    state: dict[str, Any],
    name: str,
    extra: dict[str, Any] | None = None,
    *,
    identity_keys: tuple[str, ...] = IDENTITY_KEYS,
) -> None:
    """Emit with turn identity merged from ``state`` — avoids repeating ``state.get`` boilerplate."""
    base = event_identity_from_state(state)
    payload = {key: base[key] for key in identity_keys}
    if extra:
        payload.update(extra)
    emit(writer, name, payload)


def _field(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def memory_text(item: Any) -> str:
    """First non-empty memory field in priority order, whitespace-normalized."""
    for key in _MEMORY_TEXT_KEYS:
        value = _field(item, key)
        if value:
            return " ".join(str(value).split())
    return ""


def tool_args_one_line(args: dict[str, Any], *, max_len: int = AGENT_TOOL_ARGS_MAX) -> str:
    try:
        text = json.dumps(args, ensure_ascii=False, default=str, separators=(",", ":"))
    except TypeError:
        text = str(args)
    compact = " ".join(text.split())
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3] + "..."


def tool_result_bounded(content: str, *, max_len: int = AGENT_TOOL_RESULT_MAX) -> str:
    text = str(content or "")
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def tool_call_id(call: dict[str, Any]) -> str:
    return str(call.get("id") or "")


def tool_call_name(call: dict[str, Any]) -> str:
    return str(call.get("name") or "")


def tool_call_args(call: dict[str, Any]) -> dict[str, Any]:
    args = call.get("args") or {}
    return args if isinstance(args, dict) else {}
