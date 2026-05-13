from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

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
            "model_id": "openai:gpt-test",
        },
    )
    await sub.dispatch(
        inbound,
        GRAPH_LLM_USAGE,
        {
            "inbound_id": inbound.routing.id,
            "chat_channel_id": channel.id,
            "model_id": "openai:gpt-test",
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
            "model_id": "openai:gpt-test",
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
    assert "text_reply_completed_at" in inbound_agent
    assert "completed_at" not in inbound_agent
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
    assert "completed_at" in inbound_agent
    assert reply_agent == inbound_agent


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
    assert "completed_at" in agent
