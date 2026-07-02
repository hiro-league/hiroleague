"""Pin every ``@graph_logged`` node's declared ``on_error`` policy (review §2.2).

The policy (``raise`` | ``degrade`` | ``mixed``) is the single auditable annotation for how
each node handles its own failures. This test makes it a drift gate: changing a node's
error policy — or adding/removing a ``@graph_logged`` node — must update the registry here,
forcing the change to be deliberate.

It does NOT assert runtime degrade behavior — that's covered per-node by the dedicated
failure tests (``test_rerank_node_falls_back_on_error``, ``test_graph_fetch_*``,
``test_store_turn_memory_*``, etc.). This is purely the declared-policy contract.
"""

from __future__ import annotations

import pytest

from hirocli.runtime.agent_graph.ledger import ON_ERROR_VALUES, graph_logged, graph_logged_spec
from hirocli.runtime.agent_graph.node_group import NodeGroup
from hirocli.runtime.agent_graph.nodes.context import ContextNodes
from hirocli.runtime.agent_graph.nodes.knowledge import KnowledgeFanoutNodes
from hirocli.runtime.agent_graph.nodes.llm import LLMNodes
from hirocli.runtime.agent_graph.nodes.media import MediaNodes
from hirocli.runtime.agent_graph.nodes.memory import MemoryNodes
from hirocli.runtime.agent_graph.nodes.tts import TTSNodes
from hirocli.services.knowledge.agent.answer_nodes import KnowledgeAnswerNodes
from hirocli.services.knowledge.agent.retrieval_nodes import KnowledgeRetrievalNodes

# Declared error policy per group, keyed by LangGraph node label. Only ``@graph_logged``
# nodes appear — unlogged pure-transform nodes (``parse_query``, ``build_filters``,
# ``trim_history``, ``context_build``, ``ingest``, ``gather``) carry no policy.
EXPECTED_POLICY: dict[type[NodeGroup], dict[str, str]] = {
    MediaNodes: {"stt": "degrade", "vision": "degrade", "media_failed": "raise"},
    ContextNodes: {"compose_context": "raise"},
    MemoryNodes: {"memory_recall": "degrade", "memory_out": "raise"},
    KnowledgeFanoutNodes: {"knowledge_retrieve": "degrade"},
    LLMNodes: {"call_model": "raise", "tools": "degrade"},
    TTSNodes: {"tts": "degrade", "finalize": "raise"},
    KnowledgeRetrievalNodes: {
        "rewrite_query": "degrade",
        "graph_expand": "degrade",
        "graph_fetch": "degrade",
        "embed_query": "mixed",
        "vector_search": "raise",
        "rerank": "degrade",
        "build_context": "raise",
    },
    KnowledgeAnswerNodes: {"call_model": "degrade", "finalize": "raise"},
}


def _logged_policies(group_cls: type[NodeGroup]) -> dict[str, str]:
    """Map node label → declared ``on_error`` for every ``@graph_logged`` method on the group."""
    out: dict[str, str] = {}
    for label, attr_name in group_cls.node_methods().items():
        spec = graph_logged_spec(getattr(group_cls, attr_name))
        if spec is not None:
            out[label] = spec.on_error
    return out


@pytest.mark.parametrize("group_cls", list(EXPECTED_POLICY))
def test_node_error_policy_matches_registry(group_cls: type[NodeGroup]) -> None:
    assert _logged_policies(group_cls) == EXPECTED_POLICY[group_cls]


def test_every_declared_policy_is_valid() -> None:
    for policies in EXPECTED_POLICY.values():
        for value in policies.values():
            assert value in ON_ERROR_VALUES


def test_graph_logged_rejects_unknown_policy() -> None:
    with pytest.raises(ValueError, match="on_error must be one of"):
        graph_logged(on_error="swallow")
