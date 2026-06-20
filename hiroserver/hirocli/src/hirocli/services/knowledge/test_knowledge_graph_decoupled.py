"""Boundary guard: ``KnowledgeAgentGraph`` inherits ``NodeGroup``, not chat graph classes."""

from __future__ import annotations

import importlib

from hirocli.runtime.agent_graph.node_group import NodeGroup
from hirocli.services.knowledge.agent.graph import KnowledgeAgentGraph


def test_knowledge_graph_inherits_node_group_not_chat_base() -> None:
    assert issubclass(KnowledgeAgentGraph, NodeGroup)


def test_knowledge_graph_does_not_import_agent_graph_base() -> None:
    graph_mod = importlib.import_module("hirocli.services.knowledge.agent.graph")
    assert "hirocli.runtime.agent_graph.base" not in graph_mod.__dict__.values()
