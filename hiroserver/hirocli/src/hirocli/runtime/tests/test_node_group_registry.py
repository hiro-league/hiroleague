"""``NodeGroup.node_methods`` / ``registered_nodes`` registry tests (P1a)."""

from __future__ import annotations

from pathlib import Path

from hirocli.domain.data_store import ensure_data_db
from hirocli.runtime.agent_graph import ChatAgentGraph, ChatGraphConfig
from hirocli.runtime.agent_graph.nodes.conversation import ConversationNodes
from hirocli.runtime.agent_graph.nodes.media import MediaNodes
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime
from hirocli.runtime.tests.graph_fakes import ScriptedChatModel, make_agent_services

MEDIA_NODE_LABELS = frozenset({"ingest", "stt", "vision", "gather", "media_failed"})

CONVERSATION_NODE_LABELS = frozenset(
    {
        "trim_history",
        "memory_search",
        "context_build",
        "compose_context",
        "call_model",
        "memory_out",
        "tts",
        "finalize",
        "tools",
        "knowledge_retrieve",
    }
)


def test_media_node_methods_labels() -> None:
    assert set(MediaNodes.node_methods()) == MEDIA_NODE_LABELS


def test_conversation_node_methods_labels() -> None:
    assert set(ConversationNodes.node_methods()) == CONVERSATION_NODE_LABELS


def test_conversation_registration_order_matches_builder(tmp_path: Path) -> None:
    ensure_data_db(tmp_path)
    runtime = WorkspacePreferencesRuntime(tmp_path)
    services = make_agent_services(tmp_path, preferences=runtime)
    config = ChatGraphConfig(
        model=ScriptedChatModel(responses=[]),
        tools=[],
        model_id="fake:model",
        system_prompt=None,
    )
    conv = ConversationNodes(services, config)
    compiled = ChatAgentGraph(services).build(config)
    conv_labels = [label for label in conv.registered_nodes() if label in compiled.builder.nodes]
    builder_labels = [
        name
        for name in compiled.builder.nodes
        if name not in ("__start__", "__end__") and name in CONVERSATION_NODE_LABELS
    ]
    assert conv_labels == builder_labels


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
