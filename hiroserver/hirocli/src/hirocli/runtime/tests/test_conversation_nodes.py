"""Unit tests across the conversation-side node groups (LLM, Context, Memory, TTS).

After the §1.5 split, ``ConversationNodes`` no longer exists — these tests now exercise
the individual cluster groups directly. The factory helpers below build whichever group
each test needs, keeping the per-test surface narrow.
"""

from __future__ import annotations

import base64
from pathlib import Path

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
    FakeVoiceEngine,
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
    prefs: WorkspacePreferencesRuntime | None = None,
) -> TTSNodes:
    return TTSNodes(make_agent_services(tmp_path, preferences=prefs))


def _voice(profile_id: str = "hiro-voice"):
    """A resolved voice (Phase 7b step 5: voice replies speak with voice profiles)."""
    from hirocli.domain.preferences import ResolvedVoice, VoiceProfile

    profile = VoiceProfile(label="Hiro's voice", model="google:gemini-3.8-flash-tts", voice="kore", style="warm")
    return ResolvedVoice(profile_id=profile_id, profile=profile, source="hiro")


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
async def test_tts_gate_routing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hirocli.domain.preferences.resolve_character_voice", lambda *a, **k: _voice())
    tts = _tts(tmp_path)
    assert tts.tts_gate({"reply_text": "hi", "request_voice_reply": True}) == "tts"
    assert tts.tts_gate({"reply_text": "hi", "request_voice_reply": False}) == "finalize"
    assert tts.tts_gate({"reply_text": None}) == "finalize"


@pytest.mark.asyncio
async def test_tts_gate_no_voice_profile_means_no_voice_reply(tmp_path: Path) -> None:
    # No character voice profile and no voice.hiro_profile → no voice reply.
    tts = _tts(tmp_path)
    assert tts.tts_gate({"reply_text": "hi", "request_voice_reply": True, "character_id": "hiro"}) == "finalize"


@pytest.mark.asyncio
async def test_tts_node_speaks_mp3_with_the_voice_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hirocli.services.voice import engine

    ensure_data_db(tmp_path)
    seed_default_characters(tmp_path)
    runtime = WorkspacePreferencesRuntime(tmp_path)
    monkeypatch.setattr("hirocli.domain.preferences.resolve_character_voice", lambda *a, **k: _voice())
    fake = FakeVoiceEngine(seconds=1.0)
    monkeypatch.setattr(engine, "synthesize", fake.synthesize)
    tts = _tts(tmp_path, prefs=runtime)
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
    assert fake.calls and fake.calls[0][1] == "hello there"
    assert result["reply_audio"]["media_type"] == "audio/mpeg"
    tts_events = [e for e in events if e.get("event") == GRAPH_TTS_COMPLETED]
    assert len(tts_events) == 1
    payload = tts_events[0]["payload"]
    assert payload["reply_id"] == "reply-1"
    assert payload["media_type"] == "audio/mpeg"
    assert payload["provider"] == "google"
    assert payload["model"] == "gemini-3.8-flash-tts"
    assert payload["voice"] == "kore"
    assert payload["duration_ms"] == 1000
    mp3 = base64.b64decode(payload["audio_b64"])
    # An MP3 stream: an ID3 tag or an MPEG frame sync (11 set bits).
    assert mp3[:3] == b"ID3" or (mp3[0] == 0xFF and (mp3[1] & 0xE0) == 0xE0)
    assert payload["size"] == len(mp3)


@pytest.mark.asyncio
async def test_tts_node_fills_usage_for_the_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hirocli.runtime.agent_graph.nodes.tts_support import build_tts_attachment_and_payload
    from hirocli.services.voice.kit import Speech

    speech = Speech(b"\x00\x00" * 24000, 24000, 2.0, 0.01, True, tokens_in=9, tokens_out=50)
    built = build_tts_attachment_and_payload(b"mp3", speech, _voice().profile, "hello there", reply_id="r")
    assert built.usage_counts["tts_text_tokens"] == 9
    assert built.usage_counts["tts_audio_tokens"] == 50
    assert built.usage_counts["tts_audio_seconds"] == 2.0
    assert built.payload["input_characters"] == len("hello there")
    assert built.payload["output_audio_tokens"] == 50


@pytest.mark.asyncio
async def test_tts_node_no_voice_profile_skips(tmp_path: Path) -> None:
    ensure_data_db(tmp_path)
    seed_default_characters(tmp_path)
    tts = _tts(tmp_path, prefs=WorkspacePreferencesRuntime(tmp_path))
    events: list[dict] = []
    result = await tts.tts_node(
        {"inbound_id": "in-novoice", "chat_channel_id": 3, "character_id": "hiro", "reply_text": "hello"},
        events.append,
    )
    assert result == {}
    assert not any(e.get("event") == GRAPH_TTS_COMPLETED for e in events)


@pytest.mark.asyncio
async def test_tts_node_engine_failure_degrades(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hirocli.services.voice import engine

    monkeypatch.setattr("hirocli.domain.preferences.resolve_character_voice", lambda *a, **k: _voice())
    monkeypatch.setattr(engine, "synthesize", FakeVoiceEngine(mode="fail").synthesize)
    tts = _tts(tmp_path)
    events: list[dict] = []
    result = await tts.tts_node(
        {"inbound_id": "in-fail", "chat_channel_id": 3, "character_id": "hiro", "reply_text": "hello"},
        events.append,
    )
    assert result == {}
    assert not any(e.get("event") == GRAPH_TTS_COMPLETED for e in events)


@pytest.mark.asyncio
async def test_tts_node_skips_missing_character(tmp_path: Path) -> None:
    tts = _tts(tmp_path)
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
