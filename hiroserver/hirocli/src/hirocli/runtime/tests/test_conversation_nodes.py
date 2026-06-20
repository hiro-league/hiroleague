"""Unit tests for ``ConversationNodes`` — isolated over fake ``AgentServices`` (P4 §6.2)."""

from __future__ import annotations

from pathlib import Path

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from hirocli.domain.character import seed_default_characters
from hirocli.domain.data_store import ensure_data_db
from hirocli.runtime.agent_graph.config import ChatGraphConfig
from hirocli.runtime.agent_graph.events import GRAPH_LLM_USAGE, GRAPH_TTS_COMPLETED
from hirocli.runtime.agent_graph.nodes.conversation import ConversationNodes
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime
from hirocli.runtime.tests.graph_fakes import (
    FakeMemory,
    FakeTTS,
    RecordingLedgerSink,
    ScriptedChatModel,
    ai_text,
    ai_tool_call,
    echo_tool,
    make_agent_services,
)


def _conv(
    tmp_path: Path,
    *,
    responses: list | None = None,
    tools: list | None = None,
    memory=None,
    tts=None,
    prefs: WorkspacePreferencesRuntime | None = None,
    ledger_sink: RecordingLedgerSink | None = None,
) -> ConversationNodes:
    services = make_agent_services(
        tmp_path,
        memory=memory,
        tts=tts,
        preferences=prefs,
        ledger_sink=ledger_sink,
    )
    return ConversationNodes(
        services,
        ChatGraphConfig(
            model=ScriptedChatModel(responses=responses or []),
            tools=tools or [],
            model_id="fake:model",
            system_prompt="You are Hiro.",
            temperature=0.5,
            max_tokens=128,
        ),
    )


@pytest.mark.asyncio
async def test_call_model_emits_llm_usage(tmp_path: Path) -> None:
    conv = _conv(tmp_path, responses=[ai_text("hi")])
    events: list[dict] = []
    result = await conv.call_model_node(
        {"messages": [], "inbound_id": "in-1", "chat_channel_id": 1, "model_id": "fake:model"},
        events.append,
    )
    assert result == {}

    conv2 = _conv(tmp_path, responses=[ai_text("hi")])
    events = []
    result = await conv2.call_model_node(
        {
            "messages": [AIMessage(content="prior"), AIMessage(content="ignored")],
            "inbound_id": "in-1",
            "chat_channel_id": 1,
            "model_id": "fake:model",
        },
        events.append,
    )
    # With messages present, model returns scripted reply.
    assert isinstance(result["messages"][0], AIMessage)
    assert any(e.get("event") == GRAPH_LLM_USAGE for e in events)


@pytest.mark.asyncio
async def test_tools_node_produces_tool_message(tmp_path: Path) -> None:
    sink = RecordingLedgerSink(tmp_path)
    conv = _conv(
        tmp_path,
        responses=[ai_tool_call("echo_tool", {"text": "ping"}), ai_text("done")],
        tools=[echo_tool],
        ledger_sink=sink,
    )
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "echo_tool", "args": {"text": "ping"}, "id": "c1"}],
            )
        ],
        "inbound_id": "in-1",
        "chat_channel_id": 1,
    }
    result = await conv.tools_node(state, lambda _e: None)
    assert result["messages"][0].content == "echo: ping"
    assert "tools/echo_tool" in sink.nodes()


@pytest.mark.asyncio
async def test_compose_context_writes_turn_context_not_messages(tmp_path: Path) -> None:
    ensure_data_db(tmp_path)
    runtime = WorkspacePreferencesRuntime(tmp_path)
    conv = _conv(tmp_path, prefs=runtime)
    result = await conv.compose_context_node(
        {
            "retrieved_memories": [{"memory": "likes tea"}],
            "knowledge_sources": [],
        },
        lambda _e: None,
    )
    assert "turn_context" in result
    assert "messages" not in result
    assert "Memories retrieved" in result["turn_context"]


@pytest.mark.asyncio
async def test_memory_search_with_fake_memory(tmp_path: Path) -> None:
    ensure_data_db(tmp_path)
    runtime = WorkspacePreferencesRuntime(tmp_path)
    runtime.update_many({"memory.enabled": True})
    conv = _conv(tmp_path, memory=FakeMemory(), prefs=runtime)
    result = await conv.memory_search_node(
        {"user_text": "hello", "character_id": "hiro"},
        lambda _e: None,
    )
    assert len(result.get("retrieved_memories") or []) >= 1


@pytest.mark.asyncio
async def test_tts_gate_routing(tmp_path: Path) -> None:
    conv = _conv(tmp_path, tts=FakeTTS())
    assert conv.tts_gate({"reply_text": "hi", "request_voice_reply": True}) == "tts"
    assert conv.tts_gate({"reply_text": "hi", "request_voice_reply": False}) == "finalize"
    assert conv.tts_gate({"reply_text": None}) == "finalize"


@pytest.mark.asyncio
async def test_tts_node_emits_completed_with_fake_tts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_data_db(tmp_path)
    seed_default_characters(tmp_path)
    runtime = WorkspacePreferencesRuntime(tmp_path)
    monkeypatch.setattr(
        "hirocli.domain.preferences.resolve_character_voice",
        lambda *a, **k: SimpleNamespace(
            model="fake:tts", voice="alloy", instructions=None
        ),
    )
    conv = _conv(tmp_path, tts=FakeTTS(), prefs=runtime)
    events: list[dict] = []
    result = await conv.tts_node(
        {
            "inbound_id": "in-tts",
            "chat_channel_id": 3,
            "character_id": "hiro",
            "reply_text": "hello there",
            "reply_id": "reply-1",
        },
        events.append,
    )
    assert result["reply_audio"]["media_type"] == "audio/mpeg"
    tts_events = [e for e in events if e.get("event") == GRAPH_TTS_COMPLETED]
    assert len(tts_events) == 1
    payload = tts_events[0]["payload"]
    assert payload["reply_id"] == "reply-1"
    assert payload["model"]
    assert payload["voice"]
    assert payload["audio_b64"]


@pytest.mark.asyncio
async def test_tts_node_skips_missing_character(tmp_path: Path) -> None:
    conv = _conv(tmp_path, tts=FakeTTS())
    events: list[dict] = []
    result = await conv.tts_node(
        {
            "inbound_id": "in-tts-skip",
            "chat_channel_id": 3,
            "character_id": "missing-char",
            "reply_text": "hello",
        },
        events.append,
    )
    assert result == {}
    assert not any(e.get("event") == GRAPH_TTS_COMPLETED for e in events)
