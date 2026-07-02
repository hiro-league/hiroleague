"""Characterization net for ``ChatAgentGraph`` (docs §5.2).

Black-box tests over the *compiled* chat graph: drive a canned inbound through fakes and assert
the observable contract — ordered ``GRAPH_*`` events, final state, and the ledger rows each node
flushes. These are intentionally **internals-agnostic**: they pin behavior so the agent-graph
refactor (``docs/agent-graph-refactor-design.md``) can move code underneath them. A diff that
turns one of these red is a regression, not a refactor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hirocli.domain.data_store import ensure_data_db, get_default_user_id
from hirocli.runtime.agent_graph import ChatAgentGraph, ChatGraphConfig
from hirocli.runtime.agent_graph.events import (
    GRAPH_ERROR,
    GRAPH_INGEST_COMPLETED,
    GRAPH_LLM_USAGE,
    GRAPH_MEMORY_STORED,
    GRAPH_REPLY_COMPLETED,
    GRAPH_RUN_COMPLETED,
    GRAPH_STT_COMPLETED,
    GRAPH_TOOL_COMPLETED,
)
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime
from hirocli.runtime.tests.graph_fakes import (
    FakeKnowledgeSubgraph,
    FakeMemory,
    FakeSTT,
    RecordingLedgerSink,
    ScriptedChatModel,
    ai_text,
    ai_tool_call,
    echo_tool,
    make_agent_services,
    make_inbound_envelope,
    run_graph,
)


def _build_chat(
    tmp_path: Path,
    *,
    responses: list[Any],
    tools: tuple = (),
    memory: FakeMemory | None = None,
    knowledge_subgraph: Any = None,
    stt: Any = None,
    prefs_overrides: dict[str, Any] | None = None,
) -> tuple[Any, RecordingLedgerSink, WorkspacePreferencesRuntime]:
    ensure_data_db(tmp_path)
    runtime = WorkspacePreferencesRuntime(tmp_path)
    runtime.update_many({"memory.enabled": True, **(prefs_overrides or {})})
    sink = RecordingLedgerSink(tmp_path)
    services = make_agent_services(
        tmp_path,
        ledger_sink=sink,
        preferences=runtime,
        stt=stt,
        memory=memory,
        knowledge_subgraph=knowledge_subgraph,
    )
    graph = ChatAgentGraph(services)
    compiled = graph.build(
        ChatGraphConfig(
            model=ScriptedChatModel(responses=responses),
            tools=list(tools),
            model_id="fake:model",
            system_prompt="You are Hiro.",
            temperature=0.5,
            max_tokens=128,
            thinking=None,
        )
    )
    return compiled, sink, runtime


def _state(tmp_path: Path, envelope: dict[str, Any], **over: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "inbound_id": "in-1",
        "chat_channel_id": 1,
        "thread_id": "t-1",
        "character_id": "hiro",
        "data_user_id": get_default_user_id(tmp_path),
        "model_id": "fake:model",
        "request_voice_reply": False,
        "voice_input_allowed": True,
        "tools_enabled": True,
        "knowledge_enabled": True,
        "inbound_envelope": envelope,
        "routing_metadata": {},
        "messages": [],
    }
    state.update(over)
    return state


# ---------------------------------------------------------------------------
# Scenario 1 — text only, memory on, no tools, no knowledge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_only_turn_contract(tmp_path: Path) -> None:
    compiled, sink, _ = _build_chat(
        tmp_path, responses=[ai_text("final reply")], memory=FakeMemory()
    )
    env = make_inbound_envelope(text="hello there")
    result = await run_graph(compiled, _state(tmp_path, env))

    # Events — exact ordered sequence for this linear flow. No GRAPH_MEMORY_RETRIEVED: the P2
    # recall node runs the agentic loop, which needs a chat model; this harness configures none, so
    # recall bails ("no_model") and emits no retrieval event. (Recall behavior: test_retrieval_agent
    # + test_agent_graph_preferences.)
    assert result.event_names() == [
        GRAPH_INGEST_COMPLETED,
        GRAPH_LLM_USAGE,
        GRAPH_REPLY_COMPLETED,
        GRAPH_MEMORY_STORED,
        GRAPH_RUN_COMPLETED,
    ]
    # Final state — reply produced; context never leaked into durable history.
    assert result.final["reply_text"] == "final reply"
    assert result.final.get("reply_id", "").startswith("reply-")
    history = " ".join(str(getattr(m, "content", "")) for m in result.final.get("messages", []))
    assert "## Instructions" not in history and "Memories retrieved" not in history
    # Ledger — the @graph_logged nodes flushed with the expected decisions.
    nodes = set(sink.nodes())
    assert {"memory_search", "compose_context", "call_model", "memory_out", "finalize"} <= nodes
    decisions = sink.decisions()
    assert decisions["call_model"][0] == "text_reply"
    assert decisions["memory_out"][0] == "stored"
    assert decisions["finalize"][0] == "completed"
    assert sink.has_usage("call_model")


# ---------------------------------------------------------------------------
# Scenario 2 — tools loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_loop_contract(tmp_path: Path) -> None:
    compiled, sink, _ = _build_chat(
        tmp_path,
        responses=[ai_tool_call("echo_tool", {"text": "ping"}), ai_text("final reply")],
        tools=(echo_tool,),
        memory=FakeMemory(),
    )
    env = make_inbound_envelope(text="use the echo tool")
    result = await run_graph(compiled, _state(tmp_path, env))

    names = result.event_names()
    assert GRAPH_TOOL_COMPLETED in names
    # Two model invocations: the tool-call turn + the final text turn.
    assert names.count(GRAPH_LLM_USAGE) == 2
    assert result.final["reply_text"] == "final reply"
    tool_payload = result.event_payload(GRAPH_TOOL_COMPLETED)
    assert tool_payload is not None
    assert tool_payload["tool_name"] == "echo_tool"
    assert tool_payload["status"] == "completed"
    # The tool child row is recorded under the tools node.
    assert "tools/echo_tool" in sink.nodes()


# ---------------------------------------------------------------------------
# Scenario 3 — audio with successful STT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audio_stt_success_contract(tmp_path: Path) -> None:
    compiled, sink, _ = _build_chat(
        tmp_path, responses=[ai_text("got your voice note")], memory=FakeMemory(), stt=FakeSTT()
    )
    env = make_inbound_envelope(audio="AAAA")
    result = await run_graph(compiled, _state(tmp_path, env))

    names = result.event_names()
    assert names[0] == GRAPH_INGEST_COMPLETED
    assert GRAPH_STT_COMPLETED in names
    assert result.final["reply_text"] == "got your voice note"
    # gather composed user_text from the transcript and cleared the audio bytes from state.
    assert result.final.get("user_text") == "hello from audio"
    assert result.final.get("audio_items") == []
    assert "stt" in sink.nodes()


# ---------------------------------------------------------------------------
# Scenario 4 — audio-only, STT fails → media_failed short-circuit (no LLM)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audio_stt_failure_short_circuits_llm(tmp_path: Path) -> None:
    compiled, sink, _ = _build_chat(
        tmp_path,
        responses=[ai_text("should never be used")],
        memory=FakeMemory(),
        stt=FakeSTT(mode="fail"),
    )
    env = make_inbound_envelope(audio="AAAA")
    result = await run_graph(compiled, _state(tmp_path, env))

    names = result.event_names()
    assert GRAPH_ERROR in names
    assert GRAPH_REPLY_COMPLETED in names
    assert GRAPH_RUN_COMPLETED in names
    # The whole point of the gate: the LLM is never invoked on an empty turn.
    assert GRAPH_LLM_USAGE not in names
    assert result.final["reply_text"].startswith("Sorry")
    assert "media_failed" in sink.nodes()
    assert "call_model" not in sink.nodes()


# ---------------------------------------------------------------------------
# Scenario 5 — knowledge branch on (with citations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_knowledge_branch_on_attaches_sources(tmp_path: Path) -> None:
    compiled, sink, _ = _build_chat(
        tmp_path,
        responses=[ai_text("answer with knowledge")],
        memory=FakeMemory(),
        knowledge_subgraph=FakeKnowledgeSubgraph(),
        prefs_overrides={"chat.cite_sources": True},
    )
    env = make_inbound_envelope(text="what is hiro?")
    result = await run_graph(compiled, _state(tmp_path, env))

    assert result.final["reply_text"] == "answer with knowledge"
    # knowledge_retrieve ran in parallel with memory_search and retrieved a source.
    assert "knowledge_retrieve" in sink.nodes()
    assert sink.decisions()["knowledge_retrieve"][0] == "retrieved"
    reply_payload = result.event_payload(GRAPH_REPLY_COMPLETED)
    assert reply_payload is not None
    assert len(reply_payload.get("knowledge_sources") or []) == 1


# ---------------------------------------------------------------------------
# Scenario 6 — knowledge wired but per-message toggle off
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_knowledge_toggle_off_skips_branch(tmp_path: Path) -> None:
    compiled, sink, _ = _build_chat(
        tmp_path,
        responses=[ai_text("answer without knowledge")],
        memory=FakeMemory(),
        knowledge_subgraph=FakeKnowledgeSubgraph(),
    )
    env = make_inbound_envelope(text="just chatting")
    result = await run_graph(compiled, _state(tmp_path, env, knowledge_enabled=False))

    assert result.final["reply_text"] == "answer without knowledge"
    assert "knowledge_retrieve" not in sink.nodes()
    assert "memory_search" in sink.nodes()
