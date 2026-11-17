"""Unit tests for knowledge query-rewrite helpers (P2c)."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from hiro_memory.knowledge.agent.helpers import NormalizedQuery, QueryRewrite
from hiro_memory.knowledge.agent.rewrite_support import (
    dedupe_query_entities,
    parse_rewrite_result,
    rewrite_state_update,
)


def test_parse_rewrite_result_success() -> None:
    raw = AIMessage(
        content="{}",
        usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
    )
    outcome = parse_rewrite_result(
        {
            "parsed": QueryRewrite(standalone_query="rewritten", keywords=["a"]),
            "raw": raw,
        },
        model_id="google:gemini-3-flash-preview",
        inbound_id="in-1",
        chat_channel_id=7,
        estimated_input_tokens=10,
    )
    assert outcome.parsed is not None
    assert outcome.fail is None
    assert outcome.usage_payload is not None
    assert outcome.usage_payload["input_tokens"] == 3


def test_parse_rewrite_result_unparsed() -> None:
    outcome = parse_rewrite_result(
        {"parsed": None, "raw": None, "parsing_error": "bad json"},
        model_id="google:gemini-3-flash-preview",
        inbound_id="in-1",
        chat_channel_id=7,
        estimated_input_tokens=10,
    )
    assert outcome.parsed is None
    assert outcome.fail is not None
    assert outcome.fail["code"] == "rewrite_unparsed"


def test_rewrite_state_update_dedupes_entities() -> None:
    normalized = NormalizedQuery(raw="q", text="q", language="en")
    parsed = QueryRewrite(
        standalone_query="  new query  ",
        keywords=["  kw ", "kw"],
        knowledge_needed=True,
        entities=["Hiro", " Hiro ", ""],
    )
    update = rewrite_state_update(parsed, normalized)
    assert update["rewritten_query"] == "new query"
    assert update["rewrite_keywords"] == ["kw", "kw"]
    assert update["query_entities"] == ["Hiro"]


def test_dedupe_query_entities_preserves_order() -> None:
    assert dedupe_query_entities(["b", "a", "b", " c "]) == ["b", "a", "c"]
