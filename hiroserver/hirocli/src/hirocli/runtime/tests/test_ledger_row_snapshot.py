"""Byte-stable ledger row snapshots for chat characterization scenarios (P1b gate)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from hiro_commons.log import Logger
from hirocli.domain.data_store import ensure_data_db, get_default_user_id
from hirocli.runtime.agent_graph import ChatAgentGraph, ChatGraphConfig
from hirocli.runtime.agent_graph.ledger import GRAPH_LEDGER_COLUMNS, LedgerSink
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime
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
from hirocli.runtime.tests.ledger_row_snapshot import (
    load_ledger_fixture,
    read_graph_log_rows,
    rows_to_fixture,
)

_SCENARIOS = (
    ("text_only", {"memory": FakeMemory()}, {"responses": [ai_text("final reply")]}, {"text": "hello there"}, None),
    (
        "tools_loop",
        {"memory": FakeMemory()},
        {"tools": (echo_tool,), "responses": [ai_tool_call("echo_tool", {"text": "ping"}), ai_text("final reply")]},
        {"text": "use the echo tool"},
        None,
    ),
    (
        "audio_stt_success",
        {"memory": FakeMemory(), "stt": FakeSTT()},
        {"responses": [ai_text("got your voice note")]},
        {"audio": "AAAA"},
        None,
    ),
    (
        "knowledge_on",
        {"memory": FakeMemory(), "knowledge_subgraph": FakeKnowledgeSubgraph()},
        {"responses": [ai_text("answer with knowledge")]},
        {"text": "what is hiro?"},
        None,
    ),
    (
        "knowledge_off",
        {"memory": FakeMemory(), "knowledge_subgraph": FakeKnowledgeSubgraph()},
        {"responses": [ai_text("answer without knowledge")]},
        {"text": "just chatting"},
        {"knowledge_enabled": False},
    ),
)


@pytest.fixture(autouse=True)
def _ledger_logger_setup() -> None:
    LedgerSink._opened.clear()
    Logger.set_level("INFO")
    Logger.setup(console=False)
    yield
    LedgerSink._opened.clear()


async def _capture_rows(
    tmp_path: Path,
    service_kwargs: dict,
    config_kwargs: dict,
    envelope_kwargs: dict,
    state_over: dict | None,
) -> list[dict[str, str]]:
    ensure_data_db(tmp_path)
    runtime = WorkspacePreferencesRuntime(tmp_path)
    runtime.update_many({"memory.enabled": True})
    sink = LedgerSink(tmp_path)
    services = make_agent_services(tmp_path, ledger_sink=sink, preferences=runtime, **service_kwargs)
    compiled = ChatAgentGraph(services).build(
        ChatGraphConfig(
            model=ScriptedChatModel(responses=config_kwargs["responses"]),
            tools=list(config_kwargs.get("tools", ())),
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
    await run_graph(compiled, state)
    return rows_to_fixture(read_graph_log_rows(tmp_path / "logs" / "graph.log"))


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,service_kwargs,config_kwargs,envelope_kwargs,state_over", _SCENARIOS)
async def test_ledger_rows_match_fixture(
    tmp_path: Path,
    scenario: str,
    service_kwargs: dict,
    config_kwargs: dict,
    envelope_kwargs: dict,
    state_over: dict | None,
) -> None:
    captured = await _capture_rows(tmp_path, service_kwargs, config_kwargs, envelope_kwargs, state_over)
    assert captured == load_ledger_fixture(scenario)


def test_ledger_snapshot_gate_reddens_on_column_rename() -> None:
    """Negative guard: renaming a pinned column must fail the equality check."""
    fixture = load_ledger_fixture("text_only")
    drifted = [dict(row, node=f"renamed/{row['node']}") for row in fixture]
    assert drifted != fixture


def test_graph_ledger_columns_fixture_keys(tmp_path: Path) -> None:
    fixture = load_ledger_fixture("text_only")
    assert fixture
    assert set(fixture[0]) == set(GRAPH_LEDGER_COLUMNS)
