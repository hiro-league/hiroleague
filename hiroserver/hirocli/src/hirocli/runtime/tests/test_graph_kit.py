"""Unit tests for ``graph_kit`` — shared helpers extracted from ``base.py``."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage

from hirocli.runtime.agent_graph.events import GRAPH_LLM_USAGE
from hirocli.runtime.agent_graph.graph_kit import (
    KNOWLEDGE_PREVIEW_MAX,
    emit,
    estimate_text_tokens,
    knowledge_results_rows,
    llm_usage_payload,
    normalize_reply_content,
    relevance_of,
    usage_from_metadata,
)


def _collect_events() -> tuple[list[dict[str, Any]], Any]:
    captured: list[dict[str, Any]] = []

    def writer(event: dict[str, Any]) -> None:
        captured.append(event)

    return captured, writer


def test_normalize_reply_content_keeps_plain_text() -> None:
    assert normalize_reply_content("Hello") == "Hello"


def test_normalize_reply_content_extracts_provider_text_blocks() -> None:
    content = [
        {
            "type": "text",
            "text": "I'm sorry, I cannot help you with that.",
            "extras": {"signature": "opaque-provider-signature"},
        }
    ]

    assert normalize_reply_content(content) == "I'm sorry, I cannot help you with that."


def test_normalize_reply_content_joins_multiple_text_blocks() -> None:
    content = [
        {"type": "text", "text": "First"},
        {"type": "non_text", "metadata": {"ignored": True}},
        {"type": "text", "text": "Second"},
    ]

    assert normalize_reply_content(content) == "First\nSecond"


def test_normalize_reply_content_none_is_empty() -> None:
    assert normalize_reply_content(None) == ""


def test_llm_usage_payload_uses_langchain_usage_metadata_only() -> None:
    msg = AIMessage(
        content="hi",
        usage_metadata={
            "input_tokens": 10,
            "output_tokens": 4,
            "total_tokens": 14,
            "input_token_details": {"cache_read": 3},
            "output_token_details": {"reasoning": 2},
        },
        response_metadata={
            "token_usage": {
                "prompt_tokens": 999,
                "completion_tokens": 999,
                "total_tokens": 1998,
            }
        },
    )

    payload = llm_usage_payload(
        msg,
        inbound_id="in-1",
        chat_channel_id=1,
        model_id="openai:gpt-test",
        estimated_input_tokens=50,
    )

    assert payload == {
        "inbound_id": "in-1",
        "chat_channel_id": 1,
        "model_id": "openai:gpt-test",
        "usage_available": True,
        "input_tokens": 10,
        "output_tokens": 4,
        "total_tokens": 14,
        "cached_input_tokens": 3,
        "reasoning_tokens": 2,
    }


def test_llm_usage_payload_falls_back_to_estimate_when_no_usage() -> None:
    msg = AIMessage(content="hi")

    payload = llm_usage_payload(
        msg,
        inbound_id="in-2",
        chat_channel_id=2,
        model_id="openai:gpt-test",
        estimated_input_tokens=42,
    )

    assert payload == {
        "inbound_id": "in-2",
        "chat_channel_id": 2,
        "model_id": "openai:gpt-test",
        "usage_available": False,
        "estimated_input_tokens": 42,
    }


def test_usage_from_metadata_extracts_nested_details() -> None:
    usage = usage_from_metadata(
        {
            "input_tokens": 5,
            "output_tokens": 2,
            "total_tokens": 7,
            "input_token_details": {"cache_read": 1},
            "output_token_details": {"reasoning": 1},
        }
    )

    assert usage == {
        "input_tokens": 5,
        "output_tokens": 2,
        "total_tokens": 7,
        "cached_input_tokens": 1,
        "reasoning_tokens": 1,
    }


def test_estimate_text_tokens_empty_is_zero() -> None:
    assert estimate_text_tokens("") == 0


def test_estimate_text_tokens_non_empty_ceil_len_over_four() -> None:
    assert estimate_text_tokens("abcd") == 1
    assert estimate_text_tokens("abcde") == 2


def test_relevance_of_prefers_relevance_then_rerank_then_score() -> None:
    assert relevance_of(SimpleNamespace(relevance=0.9, rerank_score=0.5, score=0.1)) == 0.9
    assert relevance_of(SimpleNamespace(rerank_score=0.5, score=0.1)) == 0.5
    assert relevance_of(SimpleNamespace(score=0.1)) == 0.1
    assert relevance_of(SimpleNamespace()) is None


def test_knowledge_results_rows_builds_preview_rows() -> None:
    items = [
        SimpleNamespace(ref=1, title="Doc One", text="snippet one", relevance=0.88),
        SimpleNamespace(ref=2, title="Doc Two", text="snippet two", score=0.5),
    ]

    rows = knowledge_results_rows(items)

    assert "[1] 0.88 Doc One :: snippet one" in rows
    assert "[2] 0.50 Doc Two :: snippet two" in rows


def test_knowledge_results_rows_respects_limit() -> None:
    items = [
        SimpleNamespace(ref=i, title=f"Doc {i}", text=f"text {i}", relevance=0.5)
        for i in range(1, 6)
    ]

    rows = knowledge_results_rows(items, limit=2)

    assert "Doc 1" in rows
    assert "Doc 2" in rows
    assert "Doc 3" not in rows


def test_knowledge_preview_max_constant() -> None:
    assert KNOWLEDGE_PREVIEW_MAX == 600


def test_emit_calls_writer_once_with_event_shape() -> None:
    events, writer = _collect_events()

    emit(writer, GRAPH_LLM_USAGE, {"model_id": "openai:gpt-test"})

    assert len(events) == 1
    assert events[0]["event"] == GRAPH_LLM_USAGE
    assert events[0]["payload"] == {"model_id": "openai:gpt-test"}
