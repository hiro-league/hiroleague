"""Query-rewrite structured-output parsing and the state update it makes (P2c).

Which model rewrites, and whether it can return structured output, is the owner's pick
(``KnowledgeGraphConfig.rewrite_model``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hiro_memory.replies import llm_usage_payload

from .helpers import NormalizedQuery, QueryRewrite


@dataclass(frozen=True)
class RewriteParseResult:
    parsed: QueryRewrite | None
    usage_payload: dict[str, Any] | None
    fail: dict[str, str] | None
    finish_reason: str
    parsing_error: Any


def parse_rewrite_result(
    result: Any,
    *,
    model_id: str,
    inbound_id: str,
    chat_channel_id: int,
    estimated_input_tokens: int,
) -> RewriteParseResult:
    """Inspect ``include_raw=True`` structured output — usage is recorded even on parse failure."""
    parsed = result.get("parsed") if isinstance(result, dict) else None
    raw = result.get("raw") if isinstance(result, dict) else None
    parsing_error = result.get("parsing_error") if isinstance(result, dict) else None

    usage_payload: dict[str, Any] | None = None
    if raw is not None:
        usage_payload = llm_usage_payload(
            raw,
            inbound_id=inbound_id,
            chat_channel_id=chat_channel_id,
            model_id=model_id,
            estimated_input_tokens=estimated_input_tokens,
        )

    if not isinstance(parsed, QueryRewrite):
        finish_reason = (
            str(getattr(raw, "response_metadata", {}).get("finish_reason", ""))
            if raw is not None
            else ""
        )
        return RewriteParseResult(
            parsed=None,
            usage_payload=usage_payload,
            fail={
                "code": "rewrite_unparsed",
                "message": (
                    f"unparseable structured output (finish_reason={finish_reason or 'unknown'})"
                ),
            },
            finish_reason=finish_reason,
            parsing_error=parsing_error,
        )

    return RewriteParseResult(
        parsed=parsed,
        usage_payload=usage_payload,
        fail=None,
        finish_reason="",
        parsing_error=None,
    )


def dedupe_query_entities(entities_raw: list[str] | None) -> list[str]:
    seen: dict[str, None] = {}
    for entity in entities_raw or []:
        text = (entity or "").strip()
        if text and text not in seen:
            seen[text] = None
    return list(seen)


def rewrite_state_update(
    parsed: QueryRewrite,
    normalized: NormalizedQuery,
) -> dict[str, Any]:
    new_text = (parsed.standalone_query or "").strip() or normalized.text
    keywords = [kw.strip() for kw in parsed.keywords if kw.strip()]
    knowledge_needed = bool(parsed.knowledge_needed)
    entities = dedupe_query_entities(list(parsed.entities or []))
    return {
        "normalized_query": NormalizedQuery(
            raw=normalized.raw, text=new_text, language=normalized.language
        ),
        "rewrite_keywords": keywords,
        "query_entities": entities,
        "rewritten_query": new_text,
        "knowledge_needed": knowledge_needed,
    }
