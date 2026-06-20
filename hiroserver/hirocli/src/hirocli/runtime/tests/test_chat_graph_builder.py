"""Unit tests for ``ChatAgentGraph.build`` wiring driven by ``ChatGraphConfig`` (P2)."""

from __future__ import annotations

from pathlib import Path

from langgraph.graph.state import CompiledStateGraph

from hirocli.domain.data_store import ensure_data_db
from hirocli.runtime.agent_graph import ChatAgentGraph, ChatGraphConfig
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime
from hirocli.runtime.tests.graph_fakes import FakeKnowledgeSubgraph, ScriptedChatModel, echo_tool, make_agent_services


def _node_names(compiled: CompiledStateGraph) -> set[str]:
    return set(compiled.get_graph().nodes.keys()) - {"__start__", "__end__"}


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


def test_tools_node_present_when_tools_configured(tmp_path: Path) -> None:
    compiled = _build_graph(tmp_path, tools=[echo_tool])
    assert "tools" in _node_names(compiled)


def test_tools_node_absent_when_tools_empty(tmp_path: Path) -> None:
    compiled = _build_graph(tmp_path, tools=[])
    assert "tools" not in _node_names(compiled)


def test_knowledge_retrieve_node_present_when_subgraph_wired(tmp_path: Path) -> None:
    compiled = _build_graph(tmp_path, knowledge_subgraph=FakeKnowledgeSubgraph())
    assert "knowledge_retrieve" in _node_names(compiled)


def test_knowledge_retrieve_node_absent_without_subgraph(tmp_path: Path) -> None:
    compiled = _build_graph(tmp_path, knowledge_subgraph=None)
    assert "knowledge_retrieve" not in _node_names(compiled)


def test_build_returns_compiled_state_graph(tmp_path: Path) -> None:
    compiled = _build_graph(tmp_path)
    assert isinstance(compiled, CompiledStateGraph)
