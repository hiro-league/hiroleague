"""Tests for the post-gather input gate and the media-failed short-circuit.

These cover the regression where the LLM was being invoked even when this
turn produced no usable user text (e.g. audio-only inbound + STT failure).
The gate now routes such turns to ``media_failed_node`` which emits a
canned reply and skips ``call_model`` entirely.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hirocli.runtime.agent_graph.base import BaseAgentGraph
from hirocli.runtime.agent_graph.events import GRAPH_REPLY_COMPLETED


def _graph(tmp_path: Path) -> BaseAgentGraph:
    return BaseAgentGraph(
        workspace_path=tmp_path,
        stt_service=None,
        vision_service=None,
        tts_service=None,
        credential_store=None,
        checkpointer=None,
    )


# ---------------------------------------------------------------------------
# input_gate
# ---------------------------------------------------------------------------


def test_input_gate_routes_to_memory_in_when_user_text_present(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    assert graph.input_gate({"user_text": "hello"}) == "memory_in"


def test_input_gate_routes_to_media_failed_when_user_text_empty(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    assert graph.input_gate({"user_text": ""}) == "media_failed"
    assert graph.input_gate({"user_text": None}) == "media_failed"
    assert graph.input_gate({}) == "media_failed"


def test_input_gate_treats_whitespace_only_as_empty(tmp_path: Path) -> None:
    """Whitespace-only is effectively empty — Gemini/OpenAI would either
    parrot or return no content. Skip the call."""
    graph = _graph(tmp_path)
    assert graph.input_gate({"user_text": "   \n\t  "}) == "media_failed"


# ---------------------------------------------------------------------------
# media_failed_node
# ---------------------------------------------------------------------------


def _collect_events() -> tuple[list[dict[str, Any]], Any]:
    captured: list[dict[str, Any]] = []

    def writer(event: dict[str, Any]) -> None:
        captured.append(event)

    return captured, writer


@pytest.mark.asyncio
async def test_media_failed_node_emits_canned_reply_for_stt_failure(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    events, writer = _collect_events()

    result = await graph.media_failed_node(
        {
            "inbound_id": "in-stt",
            "chat_channel_id": 1,
            "thread_id": "t-1",
            "request_voice_reply": True,
            "errors": [{"node": "stt", "item_index": 0, "error": "boom"}],
        },
        writer,
    )

    assert result["reply_text"].startswith("Sorry, I couldn't understand the audio")
    assert result["reply_id"].startswith("reply-")
    assert len(events) == 1
    payload = events[0]["payload"]
    assert events[0]["event"] == GRAPH_REPLY_COMPLETED
    assert payload["inbound_id"] == "in-stt"
    assert payload["chat_channel_id"] == 1
    assert payload["thread_id"] == "t-1"
    assert payload["reply_text"] == result["reply_text"]
    assert payload["reply_id"] == result["reply_id"]
    assert payload["request_voice_reply"] is True


@pytest.mark.asyncio
async def test_media_failed_node_message_for_vision_only_failure(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    events, writer = _collect_events()

    result = await graph.media_failed_node(
        {
            "inbound_id": "in-vis",
            "chat_channel_id": 2,
            "errors": [{"node": "vision", "item_index": 0, "error": "x"}],
        },
        writer,
    )

    assert "image" in result["reply_text"].lower()
    assert events[0]["payload"]["request_voice_reply"] is False


@pytest.mark.asyncio
async def test_media_failed_node_message_when_both_stt_and_vision_failed(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    events, writer = _collect_events()

    result = await graph.media_failed_node(
        {
            "inbound_id": "in-both",
            "chat_channel_id": 3,
            "errors": [
                {"node": "stt", "item_index": 0, "error": "x"},
                {"node": "vision", "item_index": 1, "error": "y"},
            ],
        },
        writer,
    )

    text = result["reply_text"].lower()
    assert "audio" in text and "image" in text
    assert events[0]["payload"]["reply_id"] == result["reply_id"]


@pytest.mark.asyncio
async def test_media_failed_node_message_when_no_errors_recorded(tmp_path: Path) -> None:
    """User sent something the graph didn't recognize — no STT/vision attempted."""
    graph = _graph(tmp_path)
    events, writer = _collect_events()

    result = await graph.media_failed_node(
        {"inbound_id": "in-empty", "chat_channel_id": 4},
        writer,
    )

    assert "didn't catch" in result["reply_text"].lower()
    assert events[0]["payload"]["inbound_id"] == "in-empty"
