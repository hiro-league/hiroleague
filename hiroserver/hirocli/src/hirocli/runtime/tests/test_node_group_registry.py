"""``NodeGroup.node_methods`` / ``registered_nodes`` registry tests.

Post-§1.5 the conversation side is split across five groups; this file pins the labels
each group owns plus the negative-guard test for stray ``*_node`` methods.
"""

from __future__ import annotations

from pathlib import Path

from hirocli.domain.data_store import ensure_data_db
from hirocli.runtime.agent_graph import ChatAgentGraph, ChatGraphConfig
from hirocli.runtime.agent_graph.nodes.context import ContextNodes
from hirocli.runtime.agent_graph.nodes.knowledge import KnowledgeFanoutNodes
from hirocli.runtime.agent_graph.nodes.llm import LLMNodes
from hirocli.runtime.agent_graph.nodes.media import MediaNodes
from hirocli.runtime.agent_graph.nodes.memory import MemoryNodes
from hirocli.runtime.agent_graph.nodes.tts import TTSNodes
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime
from hirocli.runtime.tests.graph_fakes import ScriptedChatModel, make_agent_services

MEDIA_NODE_LABELS = frozenset({"ingest", "stt", "vision", "gather", "media_failed"})
CONTEXT_NODE_LABELS = frozenset({"trim_history", "context_build", "compose_context"})
MEMORY_NODE_LABELS = frozenset({"memory_recall", "memory_out"})
KNOWLEDGE_NODE_LABELS = frozenset({"knowledge_retrieve"})
LLM_NODE_LABELS = frozenset({"call_model", "tools"})
TTS_NODE_LABELS = frozenset({"tts", "finalize"})

CONVERSATION_NODE_LABELS = (
    CONTEXT_NODE_LABELS
    | MEMORY_NODE_LABELS
    | KNOWLEDGE_NODE_LABELS
    | LLM_NODE_LABELS
    | TTS_NODE_LABELS
)


def test_media_node_methods_labels() -> None:
    assert set(MediaNodes.node_methods()) == MEDIA_NODE_LABELS


def test_context_node_methods_labels() -> None:
    assert set(ContextNodes.node_methods()) == CONTEXT_NODE_LABELS


def test_memory_node_methods_labels() -> None:
    assert set(MemoryNodes.node_methods()) == MEMORY_NODE_LABELS


def test_knowledge_node_methods_labels() -> None:
    assert set(KnowledgeFanoutNodes.node_methods()) == KNOWLEDGE_NODE_LABELS


def test_llm_node_methods_labels() -> None:
    assert set(LLMNodes.node_methods()) == LLM_NODE_LABELS


def test_tts_node_methods_labels() -> None:
    assert set(TTSNodes.node_methods()) == TTS_NODE_LABELS


def test_conversation_groups_cover_full_chat_surface(tmp_path: Path) -> None:
    """Together the five conversation-side groups expose every chat-side node label.

    Guards against accidentally dropping a node from a cluster (or accidentally adding it
    to two groups) without anyone noticing — the union must match the chat builder's
    full label set minus the media intake.
    """
    ensure_data_db(tmp_path)
    runtime = WorkspacePreferencesRuntime(tmp_path)
    services = make_agent_services(tmp_path, preferences=runtime)
    config = ChatGraphConfig(
        model=ScriptedChatModel(responses=[]),
        tools=[],
        model_id="fake:model",
        system_prompt=None,
    )
    compiled = ChatAgentGraph(services).build(config)
    conversation_labels = {
        name
        for name in compiled.builder.nodes
        if name not in ("__start__", "__end__") and name not in MEDIA_NODE_LABELS
    }
    # ``tools`` and ``knowledge_retrieve`` are gated off in this build (no tools, no kb subgraph).
    assert conversation_labels == CONVERSATION_NODE_LABELS - {"tools", "knowledge_retrieve"}


def test_registered_nodes_returns_bound_callables(tmp_path: Path) -> None:
    ensure_data_db(tmp_path)
    runtime = WorkspacePreferencesRuntime(tmp_path)
    services = make_agent_services(tmp_path, preferences=runtime)
    media = MediaNodes(services)
    nodes = media.registered_nodes()
    assert set(nodes) == MEDIA_NODE_LABELS
    for label in MEDIA_NODE_LABELS:
        assert callable(nodes[label])
        assert getattr(nodes[label], "_is_pre_node_wrapped", False)


def test_stray_node_would_break_media_labels_pin() -> None:
    """Negative guard: an unlisted ``*_node`` on a subclass is visible to ``node_methods``."""

    class StrayMedia(MediaNodes):
        async def orphan_probe_node(self, state):  # noqa: ARG002
            return {}

    assert "orphan_probe" in StrayMedia.node_methods()
    assert "orphan_probe" not in MEDIA_NODE_LABELS
