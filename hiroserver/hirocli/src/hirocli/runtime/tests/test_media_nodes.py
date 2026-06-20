"""Unit tests for ``MediaNodes`` — isolated over fake ``AgentServices`` (P4 §6.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.runtime.agent_graph.events import GRAPH_REPLY_COMPLETED, GRAPH_STT_COMPLETED
from hirocli.runtime.agent_graph.nodes.media import MediaNodes
from hirocli.runtime.tests.graph_fakes import FakeSTT, make_agent_services, make_inbound_envelope


def _media(tmp_path: Path, **service_kw) -> MediaNodes:
    return MediaNodes(make_agent_services(tmp_path, **service_kw))


@pytest.mark.asyncio
async def test_ingest_splits_modalities(tmp_path: Path) -> None:
    media = _media(tmp_path)
    env = make_inbound_envelope(text="hi", audio="AAAA", image="img")
    result = await media.ingest_node(
        {"inbound_id": "in-1", "inbound_envelope": env, "voice_input_allowed": True},
        lambda _e: None,
    )
    assert len(result["text_inputs"]) == 1
    assert result["text_inputs"][0] == "hi"
    assert len(result["audio_items"]) == 1
    assert len(result["image_items"]) == 1


@pytest.mark.asyncio
async def test_ingest_honors_voice_input_allowed(tmp_path: Path) -> None:
    media = _media(tmp_path)
    env = make_inbound_envelope(audio="AAAA")
    result = await media.ingest_node(
        {"inbound_id": "in-1", "inbound_envelope": env, "voice_input_allowed": False},
        lambda _e: None,
    )
    assert result["audio_items"] == []


@pytest.mark.asyncio
async def test_stt_node_ok_transcript(tmp_path: Path) -> None:
    media = _media(tmp_path, stt=FakeSTT(mode="ok"))
    events: list[dict] = []
    result = await media.stt_node(
        {
            "audio_item": {
                "item_index": 0,
                "body": b"audio",
                "mime_type": "audio/m4a",
                "duration_ms": 1000,
            },
            "inbound_id": "in-stt",
            "chat_channel_id": 1,
        },
        events.append,
    )
    assert result["transcripts"][0]["transcript"] == "hello from audio"
    assert events[0]["event"] == GRAPH_STT_COMPLETED


@pytest.mark.asyncio
async def test_stt_node_unavailable_returns_error(tmp_path: Path) -> None:
    media = _media(tmp_path, stt=FakeSTT(mode="unavailable"))
    result = await media.stt_node(
        {
            "audio_item": {"item_index": 0, "body": b"", "mime_type": "audio/m4a"},
            "inbound_id": "in-stt",
        },
        lambda _e: None,
    )
    assert result["errors"][0]["error"] == "stt_unavailable"


@pytest.mark.asyncio
async def test_gather_orders_and_clears_bytes(tmp_path: Path) -> None:
    media = _media(tmp_path)
    result = await media.gather_node(
        {
            "text_inputs": ["plain text"],
            "transcripts": [{"item_index": 1, "transcript": "spoken"}],
            "audio_items": [{"item_index": 1, "body": b"x", "mime_type": "audio/m4a"}],
            "image_items": [{"item_index": 2, "body": b"y"}],
        }
    )
    assert "plain text" in result["user_text"]
    assert "spoken" in result["user_text"]
    assert result["audio_items"] == []
    assert result["image_items"] == []


def test_input_gate_routing(tmp_path: Path) -> None:
    media = _media(tmp_path)
    assert media.input_gate({"user_text": "hi"}) == "trim_history"
    assert media.input_gate({"user_text": ""}) == "media_failed"


@pytest.mark.asyncio
async def test_media_failed_stt_canned_reply(tmp_path: Path) -> None:
    media = _media(tmp_path)
    events: list[dict] = []
    result = await media.media_failed_node(
        {
            "inbound_id": "in-fail",
            "chat_channel_id": 1,
            "errors": [{"node": "stt", "item_index": 0, "error": "x"}],
        },
        events.append,
    )
    assert "audio" in result["reply_text"].lower()
    assert events[0]["event"] == GRAPH_REPLY_COMPLETED
