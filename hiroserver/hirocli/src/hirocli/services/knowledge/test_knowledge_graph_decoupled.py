"""Boundary guard: knowledge graph composition mirrors the chat side."""

from __future__ import annotations

import importlib
from pathlib import Path

from hirocli.runtime.agent_graph.node_group import NodeGroup
from hirocli.services.knowledge.agent.graph import KnowledgeAgentGraph
from hirocli.services.knowledge.agent.nodes import KnowledgeNodes


def test_knowledge_nodes_inherits_node_group() -> None:
    assert issubclass(KnowledgeNodes, NodeGroup)


def test_knowledge_graph_builder_does_not_inherit_node_group() -> None:
    assert not issubclass(KnowledgeAgentGraph, NodeGroup)


def test_knowledge_agent_module_does_not_import_agent_graph_base() -> None:
    """The deleted ``agent_graph.base`` god-class must not reappear as an import target."""
    # Source-text check (NOT ``__dict__.values()`` — that holds module/function/class
    # objects, never dotted-name strings, so the assertion would pass vacuously).
    agent_dir = Path(__file__).resolve().parent / "agent"
    for py in agent_dir.glob("*.py"):
        src = py.read_text(encoding="utf-8")
        assert "agent_graph.base" not in src, f"{py.name} imports deleted agent_graph.base"


def test_knowledge_nodes_auto_wrapped_at_import() -> None:
    assert getattr(KnowledgeNodes.rewrite_query_node, "_is_pre_node_wrapped", False)


def test_knowledge_nodes_ledger_labels_are_prefixed() -> None:
    """``KnowledgeNodes`` opts into the ``knowledge/`` ledger prefix so its rows (a) group under
    the admin Graph Runs substep view (``graph-runs-pure.isGraphNodeSubstep``) and (b) don't
    collide with chat-side node names (``call_model``, ``finalize``) in ``LedgerSink`` counters
    or ``RunAccumulator.fold_row``."""
    assert KnowledgeNodes._ledger_label_prefix == "knowledge"
