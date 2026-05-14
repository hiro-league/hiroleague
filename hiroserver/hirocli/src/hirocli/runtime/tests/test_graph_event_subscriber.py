from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from types import MappingProxyType

from hiro_channel_sdk.models import ContentItem, MessageRouting, UnifiedMessage
from hirocli.domain.conversation_channel import CHAT_CHANNEL_ID_METADATA_KEY, create_channel
from hirocli.domain.data_store import ensure_data_db
from hirocli.domain.message_store import list_message_history
from hirocli.runtime.agent_graph import (
    GRAPH_INGEST_COMPLETED,
    GRAPH_LLM_USAGE,
    GRAPH_REPLY_COMPLETED,
    GRAPH_RUN_COMPLETED,
    GRAPH_RUN_FAILED,
    GRAPH_TOOL_COMPLETED,
    GRAPH_TTS_COMPLETED,
)
from hiro_commons.llm_usage import (
    gemini_usage_aggregate_fallback as _gemini_tts_usage_aggregate_fallback,
    modality_token_count as _modality_token_count,
)
from hirocli.runtime.graph_event_subscriber import GraphEventSubscriber


class _DeviceNames:
    def resolve(self, device_id: str) -> str:
        return device_id


@dataclass
class _Ctx:
    workspace_path: Path
    device_names: _DeviceNames


@pytest.mark.asyncio
async def test_graph_events_patch_compact_agent_metadata(tmp_path) -> None:
    ensure_data_db(tmp_path)
    channel = create_channel(tmp_path, name="telemetry", character_id="hiro", user_id=1)
    emitted: list[UnifiedMessage] = []

    async def emit(msg: UnifiedMessage) -> None:
        emitted.append(msg)

    inbound = UnifiedMessage(
        routing=MessageRouting(
            id="user-msg-telemetry",
            channel="devices",
            direction="inbound",
            sender_id="admin",
            metadata={CHAT_CHANNEL_ID_METADATA_KEY: f"server-{channel.id}"},
        ),
        content=[ContentItem(content_type="text", body="hello")],
    )
    sub = GraphEventSubscriber(
        ctx=_Ctx(workspace_path=tmp_path, device_names=_DeviceNames()),  # type: ignore[arg-type]
        emit_outbound=emit,
    )

    sub.begin_run(inbound.routing.id)
    await sub.dispatch(
        inbound,
        GRAPH_INGEST_COMPLETED,
        {
            "inbound_id": inbound.routing.id,
            "chat_channel_id": channel.id,
            "character_id": "hiro",
            "model_id": "openai:gpt-5.4-mini",
        },
    )
    await sub.dispatch(
        inbound,
        GRAPH_LLM_USAGE,
        {
            "inbound_id": inbound.routing.id,
            "chat_channel_id": channel.id,
            "model_id": "openai:gpt-5.4-mini",
            "usage_available": True,
            "input_tokens": 10,
            "output_tokens": 4,
            "total_tokens": 14,
        },
    )
    await sub.dispatch(
        inbound,
        GRAPH_LLM_USAGE,
        {
            "inbound_id": inbound.routing.id,
            "chat_channel_id": channel.id,
            "model_id": "openai:gpt-5.4-mini",
            "usage_available": True,
            "input_tokens": 3,
            "output_tokens": 2,
            "total_tokens": 5,
        },
    )
    await sub.dispatch(
        inbound,
        GRAPH_TOOL_COMPLETED,
        {
            "inbound_id": inbound.routing.id,
            "chat_channel_id": channel.id,
            "tool_call_id": "call-1",
            "tool_name": "files.head",
            "status": "completed",
            "elapsed_ms": 25,
            "error": None,
        },
    )
    await sub.dispatch(
        inbound,
        GRAPH_REPLY_COMPLETED,
        {
            "inbound_id": inbound.routing.id,
            "chat_channel_id": channel.id,
            "thread_id": str(channel.id),
            "reply_text": "hi",
            "reply_id": "reply-telemetry",
            "request_voice_reply": False,
        },
    )

    history = await list_message_history(tmp_path, channel.id, limit=None)
    by_id: dict[str, dict[str, Any]] = {str(row["id"]): row for row in history}
    inbound_agent = by_id["user-msg-telemetry"]["metadata"]["agent"]
    reply_agent = by_id["reply-telemetry"]["metadata"]["agent"]

    assert inbound_agent["status"] == "processing"
    assert inbound_agent["current_step"] == "reply_ready"
    assert inbound_agent["last_event"] == GRAPH_REPLY_COMPLETED
    assert inbound_agent["reply_id"] == "reply-telemetry"
    assert "cost" not in inbound_agent
    assert "elapsed_ms" not in inbound_agent
    assert inbound_agent["usage_total"] == {
        "input_tokens": 13,
        "output_tokens": 6,
        "total_tokens": 19,
    }
    assert "llm_calls" not in inbound_agent
    assert inbound_agent["tools"] == [
        {
            "id": "call-1",
            "name": "files.head",
            "status": "completed",
            "elapsed_ms": 25,
        }
    ]
    assert reply_agent == inbound_agent

    await sub.dispatch(
        inbound,
        GRAPH_RUN_COMPLETED,
        {
            "inbound_id": inbound.routing.id,
            "chat_channel_id": channel.id,
            "reply_id": "reply-telemetry",
        },
    )
    history = await list_message_history(tmp_path, channel.id, limit=None)
    by_id = {str(row["id"]): row for row in history}
    inbound_agent = by_id["user-msg-telemetry"]["metadata"]["agent"]
    reply_agent = by_id["reply-telemetry"]["metadata"]["agent"]
    assert inbound_agent["status"] == "completed"
    assert inbound_agent["current_step"] is None
    assert inbound_agent["last_event"] == GRAPH_RUN_COMPLETED
    assert isinstance(inbound_agent["elapsed_ms"], int)
    assert inbound_agent["cost"] == {
        "currency": "USD",
        "estimated_total": 0.00003675,
        "pricing_available": True,
    }
    assert reply_agent == inbound_agent


@pytest.mark.asyncio
async def test_tts_cost_accumulates_with_existing_llm_cost(tmp_path) -> None:
    ensure_data_db(tmp_path)
    channel = create_channel(tmp_path, name="tts-cost", character_id="hiro", user_id=1)
    emitted: list[UnifiedMessage] = []

    async def emit(msg: UnifiedMessage) -> None:
        emitted.append(msg)

    inbound = UnifiedMessage(
        routing=MessageRouting(
            id="user-msg-tts-cost",
            channel="devices",
            direction="inbound",
            sender_id="admin",
            metadata={CHAT_CHANNEL_ID_METADATA_KEY: f"server-{channel.id}"},
        ),
        content=[ContentItem(content_type="text", body="speak")],
    )
    sub = GraphEventSubscriber(
        ctx=_Ctx(workspace_path=tmp_path, device_names=_DeviceNames()),  # type: ignore[arg-type]
        emit_outbound=emit,
    )

    sub.begin_run(inbound.routing.id)
    await sub.dispatch(
        inbound,
        GRAPH_INGEST_COMPLETED,
        {
            "inbound_id": inbound.routing.id,
            "chat_channel_id": channel.id,
            "character_id": "hiro",
            "model_id": "openai:gpt-5.4-mini",
        },
    )
    await sub.dispatch(
        inbound,
        GRAPH_LLM_USAGE,
        {
            "inbound_id": inbound.routing.id,
            "chat_channel_id": channel.id,
            "model_id": "openai:gpt-5.4-mini",
            "usage_available": True,
            "input_tokens": 10,
            "output_tokens": 4,
            "total_tokens": 14,
        },
    )
    await sub.dispatch(
        inbound,
        GRAPH_REPLY_COMPLETED,
        {
            "inbound_id": inbound.routing.id,
            "chat_channel_id": channel.id,
            "thread_id": str(channel.id),
            "reply_text": "spoken reply",
            "reply_id": "reply-tts-cost",
            "request_voice_reply": True,
        },
    )
    audio_bytes = b"audio"
    await sub.dispatch(
        inbound,
        GRAPH_TTS_COMPLETED,
        {
            "inbound_id": inbound.routing.id,
            "chat_channel_id": channel.id,
            "reply_id": "reply-tts-cost",
            "media_type": "audio/mpeg",
            "size": len(audio_bytes),
            "duration_ms": 1000,
            "audio_b64": base64.b64encode(audio_bytes).decode(),
            "provider": "openai",
            "model": "tts-1",
            "voice": "sage",
            "input_characters": 1_000,
        },
    )
    await sub.dispatch(
        inbound,
        GRAPH_RUN_COMPLETED,
        {
            "inbound_id": inbound.routing.id,
            "chat_channel_id": channel.id,
            "reply_id": "reply-tts-cost",
        },
    )

    history = await list_message_history(tmp_path, channel.id, limit=None)
    by_id = {str(row["id"]): row for row in history}
    agent = by_id["reply-tts-cost"]["metadata"]["agent"]
    assert agent["cost"] == {
        "currency": "USD",
        "estimated_total": 0.0150255,
        "pricing_available": True,
    }


def test_modality_token_count_accepts_mapping_proxy_detail_rows() -> None:
    meta = {
        "promptTokensDetails": (
            MappingProxyType({"modality": "TEXT", "tokenCount": 110}),
        ),
        "candidatesTokensDetails": (
            MappingProxyType({"modality": "AUDIO", "tokenCount": 370}),
        ),
    }
    assert (
        _modality_token_count(
            meta,
            detail_keys=("promptTokensDetails",),
            modality="TEXT",
        )
        == 110
    )
    assert (
        _modality_token_count(
            meta,
            detail_keys=("candidatesTokensDetails",),
            modality="AUDIO",
        )
        == 370
    )


def test_gemini_aggregate_fallback_fills_missing_modality_totals() -> None:
    meta = {"promptTokenCount": 92, "candidatesTokenCount": 89}
    assert _gemini_tts_usage_aggregate_fallback(
        meta,
        input_text_tokens=0,
        output_audio_tokens=0,
    ) == (92, 89)


@pytest.mark.asyncio
async def test_graph_run_failed_sets_friendly_error_metadata(tmp_path) -> None:
    ensure_data_db(tmp_path)
    channel = create_channel(tmp_path, name="failures", character_id="hiro", user_id=1)
    emitted: list[UnifiedMessage] = []

    async def emit(msg: UnifiedMessage) -> None:
        emitted.append(msg)

    inbound = UnifiedMessage(
        routing=MessageRouting(
            id="user-msg-failed",
            channel="devices",
            direction="inbound",
            sender_id="admin",
            metadata={CHAT_CHANNEL_ID_METADATA_KEY: f"server-{channel.id}"},
        ),
        content=[ContentItem(content_type="text", body="hello")],
    )
    sub = GraphEventSubscriber(
        ctx=_Ctx(workspace_path=tmp_path, device_names=_DeviceNames()),  # type: ignore[arg-type]
        emit_outbound=emit,
    )

    sub.begin_run(inbound.routing.id)
    await sub.dispatch(
        inbound,
        GRAPH_INGEST_COMPLETED,
        {
            "inbound_id": inbound.routing.id,
            "chat_channel_id": channel.id,
            "character_id": "hiro",
            "model_id": "openai:gpt-test",
        },
    )
    await sub.dispatch(
        inbound,
        GRAPH_RUN_FAILED,
        {
            "inbound_id": inbound.routing.id,
            "chat_channel_id": channel.id,
            "code": "reply_generation_failed",
            "message": "I couldn't finish generating a reply.",
            "node": "finalize",
        },
    )

    history = await list_message_history(tmp_path, channel.id, limit=None)
    by_id = {str(row["id"]): row for row in history}
    agent = by_id["user-msg-failed"]["metadata"]["agent"]
    assert agent["status"] == "failed"
    assert agent["current_step"] is None
    assert agent["last_event"] == GRAPH_RUN_FAILED
    assert agent["error"] == {
        "message": "I couldn't finish generating a reply.",
        "code": "reply_generation_failed",
        "node": "finalize",
    }
    assert isinstance(agent["elapsed_ms"], int)
