"""Boundary guard: the knowledge graph's node groups are ledger node groups, and the engine never imports the core."""

from __future__ import annotations

from pathlib import Path

from hiro_memory.ledger.node_group import LedgerNodeGroup
from hiro_memory.knowledge.agent.answer_nodes import KnowledgeAnswerNodes
from hiro_memory.knowledge.agent.graph import KnowledgeAgentGraph
from hiro_memory.knowledge.agent.retrieval_nodes import KnowledgeRetrievalNodes


def test_knowledge_retrieval_nodes_inherits_node_group() -> None:
    assert issubclass(KnowledgeRetrievalNodes, LedgerNodeGroup)


def test_knowledge_answer_nodes_inherits_node_group() -> None:
    assert issubclass(KnowledgeAnswerNodes, LedgerNodeGroup)


def test_knowledge_graph_builder_does_not_inherit_node_group() -> None:
    assert not issubclass(KnowledgeAgentGraph, LedgerNodeGroup)


def test_knowledge_engine_never_imports_the_core() -> None:
    """The library never imports its owner: no ``hirocli`` import anywhere in the knowledge engine."""
    # Source-text check (NOT ``__dict__.values()`` — that holds module/function/class
    # objects, never dotted-name strings, so the assertion would pass vacuously).
    root = Path(__file__).resolve().parent
    for py in [*root.glob("*.py"), *(root / "agent").glob("*.py")]:
        if py.name.startswith("test_"):
            continue
        src = py.read_text(encoding="utf-8")
        assert "import hirocli" not in src and "from hirocli" not in src, f"{py.name} imports the core"


def test_knowledge_nodes_auto_wrapped_at_import() -> None:
    assert getattr(KnowledgeRetrievalNodes.rewrite_query_node, "_is_pre_node_wrapped", False)
    assert getattr(KnowledgeAnswerNodes.call_model_node, "_is_pre_node_wrapped", False)


def test_knowledge_nodes_ledger_labels_are_prefixed() -> None:
    """Both knowledge groups opt into the ``knowledge/`` ledger prefix so their rows (a) group
    under the admin Graph Runs substep view (``graph-runs-pure.isGraphNodeSubstep``) and (b) don't
    collide with chat-side node names (``call_model``, ``finalize``) in ``LedgerSink`` counters
    or ``RunAccumulator.fold_row``."""
    assert KnowledgeRetrievalNodes._ledger_label_prefix == "knowledge"
    assert KnowledgeAnswerNodes._ledger_label_prefix == "knowledge"
