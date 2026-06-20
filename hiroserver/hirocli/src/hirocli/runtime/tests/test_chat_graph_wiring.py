"""Compile-time wiring + topology snapshot tests for ``ChatAgentGraph`` (P1a)."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.graph.state import CompiledStateGraph

from hirocli.domain.data_store import ensure_data_db
from hirocli.runtime.agent_graph import ChatAgentGraph, ChatGraphConfig
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime
from hirocli.runtime.tests.chat_graph_topology import chat_topology, load_topology_fixture
from hirocli.runtime.tests.graph_fakes import FakeKnowledgeSubgraph, ScriptedChatModel, echo_tool, make_agent_services

_TOPOLOGY_COMBOS = (
    ("text_only", [], None),
    ("tools_on", [echo_tool], None),
    ("knowledge_on", [], FakeKnowledgeSubgraph()),
    ("tools_and_knowledge", [echo_tool], FakeKnowledgeSubgraph()),
)


def _build_graph(
    tmp_path: Path,
    *,
    tools: list | None = None,
    knowledge_subgraph: object | None = None,
) -> CompiledStateGraph:
    ensure_data_db(tmp_path)
    runtime = WorkspacePreferencesRuntime(tmp_path)
    services = make_agent_services(
        tmp_path,
        preferences=runtime,
        knowledge_subgraph=knowledge_subgraph,
    )
    graph = ChatAgentGraph(services)
    return graph.build(
        ChatGraphConfig(
            model=ScriptedChatModel(responses=[]),
            tools=tools if tools is not None else [],
            model_id="fake:model",
            system_prompt=None,
        )
    )


@pytest.mark.parametrize("combo,tools,knowledge_subgraph", _TOPOLOGY_COMBOS)
def test_chat_graph_topology_matches_fixture(
    tmp_path: Path,
    combo: str,
    tools: list,
    knowledge_subgraph: object | None,
) -> None:
    compiled = _build_graph(tmp_path, tools=tools, knowledge_subgraph=knowledge_subgraph)
    assert chat_topology(compiled) == load_topology_fixture(combo)


def test_topology_fixture_gate_reddens_on_drift() -> None:
    """Negative guard: mutating the frozen snapshot must fail the equality check."""
    fixture = load_topology_fixture("text_only")
    drifted = dict(fixture)
    drifted["node_order"] = [*fixture["node_order"], "phantom"]
    assert drifted != fixture


def test_retry_policies_match_retry_dict(tmp_path: Path) -> None:
    from hirocli.runtime.agent_graph.chat import RETRY_POLICIES

    compiled = _build_graph(tmp_path)
    topology = chat_topology(compiled)
    assert topology["retry_policies"] == {
        label: {"max_attempts": policy.max_attempts} for label, policy in RETRY_POLICIES.items()
    }
