"""Byte-stable ``GRAPH_*`` event payload contract for chat characterization scenarios (P2a).

Consumer paths pinned in ``event_payload_helpers.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hiro_commons.log import Logger
from hirocli.domain.data_store import ensure_data_db, get_default_user_id
from hirocli.runtime.agent_graph import ChatAgentGraph, ChatGraphConfig
from hirocli.runtime.agent_graph.ledger import LedgerSink
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime
from hirocli.runtime.tests.event_payload_helpers import (
    load_event_payload_fixture,
    normalize_event_stream,
)
from hirocli.runtime.tests.graph_fakes import (
    FakeKnowledgeSubgraph,
    FakeMemory,
    FakeSTT,
    ScriptedChatModel,
    ai_text,
    ai_tool_call,
    echo_tool,
    make_agent_services,
    make_inbound_envelope,
    run_graph,
)

_SCENARIOS = (
    ("text_only", {"memory": FakeMemory()}, {"responses": [ai_text("final reply")]}, {"text": "hello there"}, None, ()),
    (
        "tools_loop",
        {"memory": FakeMemory()},
        {"responses": [ai_tool_call("echo_tool", {"text": "ping"}), ai_text("final reply")]},
        {"text": "use the echo tool"},
        None,
        (echo_tool,),
    ),
    (
        "audio_stt_success",
        {"memory": FakeMemory(), "stt": FakeSTT()},
        {"responses": [ai_text("got your voice note")]},
        {"audio": "AAAA"},
        None,
        (),
    ),
    (
        "audio_stt_failure",
        {"memory": FakeMemory(), "stt": FakeSTT(mode="fail")},
        {"responses": [ai_text("should never be used")]},
        {"audio": "AAAA"},
        None,
        (),
    ),
    (
        "knowledge_on",
        {"memory": FakeMemory(), "knowledge_subgraph": FakeKnowledgeSubgraph()},
        {"responses": [ai_text("answer with knowledge")]},
        {"text": "what is hiro?"},
        None,
        (),
    ),
    (
        "knowledge_off",
        {"memory": FakeMemory(), "knowledge_subgraph": FakeKnowledgeSubgraph()},
        {"responses": [ai_text("answer without knowledge")]},
        {"text": "just chatting"},
        {"knowledge_enabled": False},
        (),
    ),
)


@pytest.fixture(autouse=True)
def _quiet_logger() -> None:
    LedgerSink._opened.clear()
    Logger.set_level("INFO")
    Logger.setup(console=False)
    yield
    LedgerSink._opened.clear()


async def _capture_events(
    tmp_path: Path,
    service_kwargs: dict,
    config_kwargs: dict,
    envelope_kwargs: dict,
    state_over: dict | None,
    tools: tuple,
) -> list[dict]:
    ensure_data_db(tmp_path)
    runtime = WorkspacePreferencesRuntime(tmp_path)
    runtime.update_many({"memory.enabled": True})
    services = make_agent_services(tmp_path, preferences=runtime, **service_kwargs)
    compiled = ChatAgentGraph(services).build(
        ChatGraphConfig(
            model=ScriptedChatModel(responses=config_kwargs["responses"]),
            tools=list(tools),
            model_id="fake:model",
            system_prompt="You are Hiro.",
        )
    )
    env = make_inbound_envelope(**envelope_kwargs)
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
        "knowledge_enabled": True,
        "inbound_envelope": env,
        "routing_metadata": {},
        "messages": [],
    }
    if state_over:
        state.update(state_over)
    result = await run_graph(compiled, state)
    return normalize_event_stream(result.events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario,service_kwargs,config_kwargs,envelope_kwargs,state_over,tools",
    _SCENARIOS,
)
async def test_event_payloads_match_fixture(
    tmp_path: Path,
    scenario: str,
    service_kwargs: dict,
    config_kwargs: dict,
    envelope_kwargs: dict,
    state_over: dict | None,
    tools: tuple,
) -> None:
    captured = await _capture_events(
        tmp_path, service_kwargs, config_kwargs, envelope_kwargs, state_over, tools
    )
    assert captured == load_event_payload_fixture(scenario)


def test_event_payload_fixture_gate_reddens_on_event_rename() -> None:
    fixture = load_event_payload_fixture("text_only")
    drifted = [dict(event, event="graph.ingest.renamed") for event in fixture]
    assert drifted != fixture
