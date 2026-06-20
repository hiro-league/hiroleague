"""P6 state contract tests — checkpoint surface, Send sub-state shape, reducer integrity."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from hirocli.domain.data_store import ensure_data_db, get_default_user_id
from hirocli.runtime.agent_graph import ChatAgentGraph, ChatGraphConfig
from hirocli.runtime.agent_graph.nodes.media import MediaNodes
from hirocli.runtime.agent_graph.state import GraphState, Transcript
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime
from hirocli.runtime.tests.graph_fakes import (
    FakeMemory,
    FakeSTT,
    FakeVision,
    ScriptedChatModel,
    ai_text,
    make_agent_services,
    make_inbound_envelope,
    run_graph,
)

_STT_SEND_KEYS = frozenset(
    {"audio_item", "inbound_id", "chat_channel_id", "character_id", "routing_metadata"}
)
_VISION_SEND_KEYS = frozenset(
    {"image_item", "inbound_id", "chat_channel_id", "character_id", "routing_metadata"}
)


def _build_checkpointed_chat(tmp_path: Path) -> tuple[Any, InMemorySaver]:
    ensure_data_db(tmp_path)
    runtime = WorkspacePreferencesRuntime(tmp_path)
    runtime.update_many({"memory.enabled": False})
    checkpointer = InMemorySaver()
    services = make_agent_services(
        tmp_path,
        preferences=runtime,
        stt=FakeSTT(text="spoken words"),
        vision=FakeVision(description="a cat"),
        checkpointer=checkpointer,
    )
    graph = ChatAgentGraph(services)
    compiled = graph.build(
        ChatGraphConfig(
            model=ScriptedChatModel(responses=[ai_text("reply one"), ai_text("reply two")]),
            tools=[],
            model_id="fake:model",
            system_prompt="You are Hiro.",
        )
    )
    return compiled, checkpointer


def _turn_state(
    tmp_path: Path,
    envelope: dict[str, Any],
    *,
    inbound_id: str,
    messages: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "inbound_id": inbound_id,
        "chat_channel_id": 1,
        "thread_id": "t1",
        "character_id": "hiro",
        "data_user_id": get_default_user_id(tmp_path),
        "model_id": "fake:model",
        "request_voice_reply": False,
        "voice_input_allowed": True,
        "tools_enabled": True,
        "knowledge_enabled": False,
        "inbound_envelope": envelope,
        "routing_metadata": {"source": "test"},
        "messages": list(messages or []),
    }


@pytest.mark.asyncio
async def test_checkpoint_surface_messages_durable_scratch_ephemeral(tmp_path: Path) -> None:
    """messages accumulates across turns; scratch fields reflect only the current turn."""
    compiled, _ = _build_checkpointed_chat(tmp_path)
    config = {"configurable": {"thread_id": "t1"}}

    env1 = make_inbound_envelope(text="turn one question")
    await run_graph(compiled, _turn_state(tmp_path, env1, inbound_id="in-1"), config=config)

    snap1 = compiled.get_state(config).values
    assert len(snap1.get("messages") or []) >= 2
    assert snap1.get("user_text") == "turn one question"

    env2 = make_inbound_envelope(text="turn two question")
    await run_graph(
        compiled,
        _turn_state(tmp_path, env2, inbound_id="in-2", messages=snap1.get("messages") or []),
        config=config,
    )

    snap2 = compiled.get_state(config).values
    messages = snap2.get("messages") or []
    assert len(messages) >= 4
    human_texts = [m.content for m in messages if isinstance(m, HumanMessage)]
    assert "turn one question" in human_texts
    assert "turn two question" in human_texts
    assert snap2.get("user_text") == "turn two question"
    assert snap2.get("user_text") != "turn one question"


@pytest.mark.asyncio
async def test_checkpoint_clears_media_bytes_after_audio_turn(tmp_path: Path) -> None:
    """gather_node clears audio_items/image_items so bytes never persist in the checkpoint."""
    compiled, _ = _build_checkpointed_chat(tmp_path)
    config = {"configurable": {"thread_id": "t1"}}
    env = make_inbound_envelope(audio="AAAA", image="imgdata")

    await run_graph(
        compiled,
        _turn_state(tmp_path, env, inbound_id="in-audio"),
        config=config,
    )

    snap = compiled.get_state(config).values
    assert snap.get("audio_items") == []
    assert snap.get("image_items") == []


@pytest.mark.asyncio
async def test_dispatch_media_send_substate_shape(tmp_path: Path) -> None:
    """Send payloads carry SttSend/VisionSend keys including ledger identity fields."""
    media = MediaNodes(make_agent_services(tmp_path, stt=FakeSTT()))
    env = make_inbound_envelope(audio="AAAA", image="imgdata")
    ingested = await media.ingest_node(
        {
            "inbound_id": "in-1",
            "chat_channel_id": 42,
            "character_id": "hiro",
            "routing_metadata": {"route": "test"},
            "inbound_envelope": env,
            "voice_input_allowed": True,
        },
        lambda _e: None,
    )
    state: GraphState = {
        "inbound_id": "in-1",
        "chat_channel_id": 42,
        "character_id": "hiro",
        "routing_metadata": {"route": "test"},
        "audio_items": ingested["audio_items"],
        "image_items": ingested["image_items"],
    }
    sends = media.dispatch_media(state)
    assert isinstance(sends, list)
    assert len(sends) == 2

    stt_send = next(s for s in sends if s.node == "stt")
    vision_send = next(s for s in sends if s.node == "vision")
    assert set(stt_send.arg.keys()) == _STT_SEND_KEYS
    assert set(vision_send.arg.keys()) == _VISION_SEND_KEYS
    assert stt_send.arg["inbound_id"] == "in-1"
    assert stt_send.arg["chat_channel_id"] == 42
    assert stt_send.arg["character_id"] == "hiro"
    assert stt_send.arg["routing_metadata"] == {"route": "test"}
    assert vision_send.arg["inbound_id"] == "in-1"
    assert vision_send.arg["chat_channel_id"] == 42
    assert vision_send.arg["character_id"] == "hiro"


def test_transcripts_reducer_concatenates_partials() -> None:
    """Reducer channels stay top-level — two partials merge by concatenation, not overwrite."""
    t1: Transcript = {
        "item_index": 0,
        "transcript": "first",
        "blob_id": None,
        "mime_type": "audio/m4a",
        "duration_ms": None,
    }
    t2: Transcript = {
        "item_index": 1,
        "transcript": "second",
        "blob_id": None,
        "mime_type": "audio/m4a",
        "duration_ms": None,
    }

    def append_a(_state: GraphState) -> dict[str, Any]:
        return {"transcripts": [t1]}

    def append_b(_state: GraphState) -> dict[str, Any]:
        return {"transcripts": [t2]}

    graph = StateGraph(GraphState)
    graph.add_node("a", append_a)
    graph.add_node("b", append_b)
    graph.add_edge(START, "a")
    graph.add_edge("a", "b")
    graph.add_edge("b", END)
    result = graph.compile().invoke({})

    transcripts = result.get("transcripts") or []
    assert len(transcripts) == 2
    assert transcripts[0]["transcript"] == "first"
    assert transcripts[1]["transcript"] == "second"
