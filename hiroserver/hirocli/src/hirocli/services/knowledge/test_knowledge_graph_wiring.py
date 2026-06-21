"""Compile-time wiring tests for ``KnowledgeAgentGraph``."""

from __future__ import annotations

from pathlib import Path

from langgraph.graph.state import CompiledStateGraph

from hirocli.domain.preferences import load_preferences
from hirocli.runtime.agent_graph.ledger import LedgerSink
from hirocli.runtime.agent_graph.services import AgentServices
from hirocli.runtime.tests.graph_fakes import FakeKnowledgeService
from hirocli.services.knowledge.agent import KnowledgeAgentGraph, KnowledgeGraphConfig

_RETRIEVAL_NODES = {
    "parse_query",
    "rewrite_query",
    "graph_expand",
    "graph_fetch",
    "build_filters",
    "embed_query",
    "vector_search",
    "rerank",
    "build_context",
}
_FULL_ONLY_NODES = {"call_model", "finalize"}


def _node_names(compiled: CompiledStateGraph) -> set[str]:
    return set(compiled.get_graph().nodes.keys()) - {"__start__", "__end__"}


def _edge_pairs(compiled: CompiledStateGraph) -> set[tuple[str, str]]:
    g = compiled.get_graph()
    pairs: set[tuple[str, str]] = set()
    for edge in g.edges:
        src = edge.source if edge.source not in ("__start__",) else "__start__"
        tgt = edge.target if edge.target not in ("__end__",) else "__end__"
        if src == "__start__" or tgt == "__end__":
            continue
        pairs.add((src, tgt))
    return pairs


def _build(tmp_path: Path, *, retrieval_only: bool = False) -> CompiledStateGraph:
    prefs = load_preferences(tmp_path)
    builder = KnowledgeAgentGraph(
        AgentServices(workspace_path=tmp_path, ledger_sink=LedgerSink(tmp_path))
    )
    config = KnowledgeGraphConfig(service=FakeKnowledgeService(), prefs=prefs)
    return builder.build_retrieval(config) if retrieval_only else builder.build(config)


def test_build_full_graph_node_set(tmp_path: Path) -> None:
    compiled = _build(tmp_path)
    assert _node_names(compiled) == _RETRIEVAL_NODES | _FULL_ONLY_NODES


def test_build_retrieval_graph_node_set(tmp_path: Path) -> None:
    compiled = _build(tmp_path, retrieval_only=True)
    assert _node_names(compiled) == _RETRIEVAL_NODES


def test_full_graph_key_edges(tmp_path: Path) -> None:
    compiled = _build(tmp_path)
    edges = _edge_pairs(compiled)
    assert ("parse_query", "rewrite_query") in edges
    assert ("vector_search", "rerank") in edges
    assert ("rerank", "build_context") in edges
    assert ("call_model", "finalize") in edges


def test_retrieval_graph_ends_at_build_context(tmp_path: Path) -> None:
    compiled = _build(tmp_path, retrieval_only=True)
    edges = _edge_pairs(compiled)
    assert ("build_context", "call_model") not in edges
    assert ("build_context", "finalize") not in edges
