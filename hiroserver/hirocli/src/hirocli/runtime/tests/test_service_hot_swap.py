"""Direct ``AgentServices`` hot-swap on a live ``ChatAgentGraph`` (P2d)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.domain.data_store import ensure_data_db, get_default_user_id
from hirocli.runtime.agent_graph import ChatAgentGraph, ChatGraphConfig
from hirocli.runtime.tests.graph_fakes import (
    FakeMemory,
    FakeSTT,
    RecordingLedgerSink,
    ScriptedChatModel,
    ai_text,
    make_agent_services,
    make_inbound_envelope,
    run_graph,
)


class _TrackingSTT(FakeSTT):
    """Fake STT that records ``transcribe`` invocations for swap assertions."""

    def __init__(self, *, tag: str, text: str) -> None:
        super().__init__(text=text)
        self.tag = tag
        self.transcribe_calls = 0

    async def transcribe(self, body: str, *, mime_type: str):
        self.transcribe_calls += 1
        return await super().transcribe(body, mime_type=mime_type)


@pytest.mark.asyncio
async def test_direct_stt_swap_used_on_next_invoke(tmp_path: Path) -> None:
    ensure_data_db(tmp_path)
    initial_stt = _TrackingSTT(tag="initial", text="ignored")
    replacement_stt = _TrackingSTT(tag="replacement", text="heard after swap")
    sink = RecordingLedgerSink(tmp_path)
    services = make_agent_services(
        tmp_path,
        ledger_sink=sink,
        stt=initial_stt,
        memory=FakeMemory(),
    )
    graph = ChatAgentGraph(services)
    compiled = graph.build(
        ChatGraphConfig(
            model=ScriptedChatModel(responses=[ai_text("voice ok")]),
            tools=[],
            model_id="fake:model",
            system_prompt="You are Hiro.",
        )
    )

    # Hot-swap the container field — same pattern as AgentManager preference reactors.
    services.stt = replacement_stt

    env = make_inbound_envelope(audio="AAAA")
    state = {
        "inbound_id": "in-1",
        "chat_channel_id": 1,
        "thread_id": "t-1",
        "character_id": "hiro",
        "data_user_id": get_default_user_id(tmp_path),
        "model_id": "fake:model",
        "request_voice_reply": False,
        "voice_input_allowed": True,
        "tools_enabled": True,
        "knowledge_enabled": False,
        "inbound_envelope": env,
        "routing_metadata": {},
        "messages": [],
    }
    result = await run_graph(compiled, state)

    assert initial_stt.transcribe_calls == 0
    assert replacement_stt.transcribe_calls == 1
    assert result.final["reply_text"] == "voice ok"
    stt_row = sink.row("stt")
    assert stt_row is not None
    assert "heard after swap" in str(stt_row.get("output_preview") or "")


def test_chat_agent_graph_has_no_service_passthrough_setters() -> None:
    for name in (
        "set_stt_service",
        "set_tts_service",
        "set_memory_service",
        "set_knowledge_subgraph",
    ):
        assert not hasattr(ChatAgentGraph, name), f"removed passthrough still present: {name}"
