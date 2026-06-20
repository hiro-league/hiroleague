"""Unit tests for ``graph_kit`` — shared helpers extracted from ``base.py``."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from hirocli.runtime.agent_graph.events import GRAPH_LLM_USAGE
from hirocli.runtime.agent_graph.graph_kit import (
    AGENT_TOOL_ARGS_MAX,
    AGENT_TOOL_RESULT_MAX,
    IDENTITY_KEYS,
    IDENTITY_PEER_KEYS,
    KNOWLEDGE_PREVIEW_MAX,
    emit,
    emit_for,
    estimate_text_tokens,
    identity_from_state,
    knowledge_results_rows,
    llm_usage_payload,
    memory_text,
    normalize_reply_content,
    relevance_of,
    tool_args_one_line,
    tool_call_args,
    tool_call_id,
    tool_call_name,
    tool_result_bounded,
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


def test_emit_for_merges_identity_and_extra() -> None:
    events, writer = _collect_events()
    state = {"inbound_id": "x", "chat_channel_id": 7, "character_id": "c"}

    emit_for(writer, state, GRAPH_LLM_USAGE, {"a": 1})

    assert events[0]["payload"] == {
        "inbound_id": "x",
        "chat_channel_id": 7,
        "character_id": "c",
        "a": 1,
    }


def test_emit_for_peer_identity_subset() -> None:
    events, writer = _collect_events()
    state = {"inbound_id": "x", "chat_channel_id": 7, "character_id": "c"}

    emit_for(
        writer,
        state,
        GRAPH_LLM_USAGE,
        {"tool_name": "echo"},
        identity_keys=IDENTITY_PEER_KEYS,
    )

    assert events[0]["payload"] == {
        "inbound_id": "x",
        "chat_channel_id": 7,
        "tool_name": "echo",
    }


def test_identity_from_state_defaults() -> None:
    assert identity_from_state({}) == {
        "inbound_id": "",
        "chat_channel_id": 0,
        "character_id": "",
    }
    assert IDENTITY_KEYS == ("inbound_id", "chat_channel_id", "character_id")


# --- P2b: parity with pre-extraction implementations (kept here intentionally) -----------------


def _legacy_memory_text_dict(item: dict[str, Any]) -> str:
    text = (
        item.get("memory")
        or item.get("text")
        or item.get("content")
        or item.get("data")
        or item.get("value")
        or ""
    )
    return " ".join(str(text or "").split())


def _legacy_memory_text_any(item: Any) -> str:
    for key in ("memory", "text", "content", "data", "value"):
        if isinstance(item, dict):
            value = item.get(key)
        else:
            value = getattr(item, key, None)
        if value:
            return " ".join(str(value).split())
    return ""


def _legacy_tool_args_one_line(args: dict[str, Any], *, max_len: int = AGENT_TOOL_ARGS_MAX) -> str:
    try:
        text = json.dumps(args, ensure_ascii=False, default=str, separators=(",", ":"))
    except TypeError:
        text = str(args)
    compact = " ".join(text.split())
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3] + "..."


def _legacy_tool_result_bounded(content: str, *, max_len: int = AGENT_TOOL_RESULT_MAX) -> str:
    text = str(content or "")
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


@pytest.mark.parametrize(
    "item",
    [
        {"memory": "  hello   world  "},
        {"text": "fallback text"},
        {"memory": "", "text": "second key wins"},
        {"memory": 0, "content": "skip falsy zero"},
        {"data": {"nested": True}},
        {},
        SimpleNamespace(memory="from attribute"),
        SimpleNamespace(text="", content="  spaced  "),
    ],
)
def test_memory_text_matches_legacy(item: Any) -> None:
    assert memory_text(item) == _legacy_memory_text_any(item)
    if isinstance(item, dict):
        assert memory_text(item) == _legacy_memory_text_dict(item)


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"text": "ping"},
        {"nested": {"a": 1, "b": [2, 3]}},
        {"emoji": "café ☕"},
    ],
)
def test_tool_args_one_line_matches_legacy(args: dict[str, Any]) -> None:
    assert tool_args_one_line(args) == _legacy_tool_args_one_line(args)
    long_args = {"blob": "x" * 3000}
    assert tool_args_one_line(long_args) == _legacy_tool_args_one_line(long_args)
    assert len(tool_args_one_line(long_args)) == AGENT_TOOL_ARGS_MAX


@pytest.mark.parametrize(
    "content",
    ["", "ok", "x" * 100, "y" * 5000],
)
def test_tool_result_bounded_matches_legacy(content: str) -> None:
    assert tool_result_bounded(content) == _legacy_tool_result_bounded(content)


@pytest.mark.parametrize(
    "call,expected_id,expected_name,expected_args",
    [
        ({"id": "tc-1", "name": "echo", "args": {"text": "hi"}}, "tc-1", "echo", {"text": "hi"}),
        ({"name": "search"}, "", "search", {}),
        ({"id": None, "args": "not-a-dict"}, "", "", {}),
    ],
)
def test_tool_call_helpers(
    call: dict[str, Any],
    expected_id: str,
    expected_name: str,
    expected_args: dict[str, Any],
) -> None:
    assert tool_call_id(call) == expected_id
    assert tool_call_name(call) == expected_name
    assert tool_call_args(call) == expected_args


def test_agent_tool_max_constants() -> None:
    assert AGENT_TOOL_ARGS_MAX == 2000
    assert AGENT_TOOL_RESULT_MAX == 4000
