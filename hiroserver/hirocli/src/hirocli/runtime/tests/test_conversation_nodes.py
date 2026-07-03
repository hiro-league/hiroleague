"""Unit tests across the conversation-side node groups (LLM, Context, Memory, TTS).

After the §1.5 split, ``ConversationNodes`` no longer exists — these tests now exercise
the individual cluster groups directly. The factory helpers below build whichever group
each test needs, keeping the per-test surface narrow.
"""

from __future__ import annotations

from pathlib import Path

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from hirocli.domain.character import seed_default_characters
from hirocli.domain.data_store import ensure_data_db
from hirocli.runtime.agent_graph.config import ChatGraphConfig
from hirocli.runtime.agent_graph.events import GRAPH_LLM_USAGE, GRAPH_TTS_COMPLETED
from hirocli.runtime.agent_graph.nodes.context import ContextNodes
from hirocli.runtime.agent_graph.nodes.llm import LLMNodes
from hirocli.runtime.agent_graph.nodes.memory import MemoryNodes
from hirocli.runtime.agent_graph.nodes.tts import TTSNodes
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


def _config(
    *,
    responses: list | None = None,
    tools: list | None = None,
) -> ChatGraphConfig:
    return ChatGraphConfig(
        model=ScriptedChatModel(responses=responses or []),
        tools=tools or [],
        model_id="fake:model",
        system_prompt="You are Hiro.",
        temperature=0.5,
        max_tokens=128,
    )


def _llm(
    tmp_path: Path,
    *,
    responses: list | None = None,
    tools: list | None = None,
    prefs: WorkspacePreferencesRuntime | None = None,
    ledger_sink: RecordingLedgerSink | None = None,
) -> LLMNodes:
    services = make_agent_services(tmp_path, preferences=prefs, ledger_sink=ledger_sink)
    return LLMNodes(services, _config(responses=responses, tools=tools))


def _context(
    tmp_path: Path, *, prefs: WorkspacePreferencesRuntime | None = None
) -> ContextNodes:
    return ContextNodes(make_agent_services(tmp_path, preferences=prefs))


def _memory(
    tmp_path: Path,
    *,
    memory=None,
    prefs: WorkspacePreferencesRuntime | None = None,
) -> MemoryNodes:
    return MemoryNodes(make_agent_services(tmp_path, memory=memory, preferences=prefs))


def _tts(
    tmp_path: Path,
    *,
    tts=None,
    prefs: WorkspacePreferencesRuntime | None = None,
) -> TTSNodes:
    return TTSNodes(make_agent_services(tmp_path, tts=tts, preferences=prefs))


@pytest.mark.asyncio
async def test_call_model_emits_llm_usage(tmp_path: Path) -> None:
    llm = _llm(tmp_path, responses=[ai_text("hi")])
    events: list[dict] = []
    result = await llm.call_model_node(
        {"messages": [], "inbound_id": "in-1", "chat_channel_id": 1, "model_id": "fake:model"},
        events.append,
    )
    assert result == {}

    llm2 = _llm(tmp_path, responses=[ai_text("hi")])
    events = []
    result = await llm2.call_model_node(
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
    llm = _llm(
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
    result = await llm.tools_node(state, lambda _e: None)
    assert result["messages"][0].content == "echo: ping"
    assert "tools/echo_tool" in sink.nodes()


@pytest.mark.asyncio
async def test_compose_context_writes_turn_context_not_messages(tmp_path: Path) -> None:
    ensure_data_db(tmp_path)
    runtime = WorkspacePreferencesRuntime(tmp_path)
    context = _context(tmp_path, prefs=runtime)
    result = await context.compose_context_node(
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
async def test_memory_recall_with_fake_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Phase 2: the node runs the agentic loop. Stub the model builder + the loop with a canned
    # result so the node test stays focused (the loop itself is covered by test_retrieval_agent).
    from hirocli.services.memory.agent import MemoryRetriever
    from hirocli.services.memory.agent.accumulator import Accumulator
    from hirocli.services.memory.agent.retrieval_agent import RetrievalResult

    ensure_data_db(tmp_path)
    runtime = WorkspacePreferencesRuntime(tmp_path)
    runtime.update_many({"memory.enabled": True})
    acc = Accumulator()
    acc.merge(
        [{"kind": "fact", "uuid": "e1", "memory": "recalled fact", "fact": "recalled fact"}],
        search_id=1,
        goal="",
    )

    async def _fake_retrieve(query, **_kw):
        return RetrievalResult(
            accumulator=acc,
            answer_text="draft",
            transcript=[{"event": "final", "cumulative_agent_turns": 1}],
        )

    monkeypatch.setattr(
        "hirocli.services.memory.models.MemoryRetrievalModelCache.get",
        lambda self, *a, **k: (object(), "fake:model"),
    )
    monkeypatch.setattr(MemoryRetriever, "retrieve", staticmethod(_fake_retrieve))

    memory = _memory(tmp_path, memory=FakeMemory(), prefs=runtime)
    result = await memory.memory_recall_node(
        {"user_text": "hello", "character_id": "hiro"},
        lambda _e: None,
    )
    assert len(result.get("retrieved_memories") or []) >= 1
    assert result.get("memory_draft") == "draft"


@pytest.mark.asyncio
async def test_tts_gate_routing(tmp_path: Path) -> None:
    tts = _tts(tmp_path, tts=FakeTTS())
    assert tts.tts_gate({"reply_text": "hi", "request_voice_reply": True}) == "tts"
    assert tts.tts_gate({"reply_text": "hi", "request_voice_reply": False}) == "finalize"
    assert tts.tts_gate({"reply_text": None}) == "finalize"


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
    tts = _tts(tmp_path, tts=FakeTTS(), prefs=runtime)
    events: list[dict] = []
    result = await tts.tts_node(
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
    tts = _tts(tmp_path, tts=FakeTTS())
    events: list[dict] = []
    result = await tts.tts_node(
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
