"""LangGraph builder for admin knowledge retrieval and answering."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from hirocli.runtime.agent_graph.ledger import LedgerSink
from hirocli.runtime.agent_graph.services import AgentServices

from .nodes import KnowledgeNodes
from .state import KnowledgeAgentState

if TYPE_CHECKING:
    from hirocli.domain.preferences import WorkspacePreferences


class KnowledgeAgentGraph:
    """Thin builder composing ``KnowledgeNodes`` into full or retrieval-only graphs."""

    def __init__(
        self,
        *,
        workspace_path: Path,
        service: Any,
        prefs: "WorkspacePreferences",
        workspace_id: str | None = None,
    ) -> None:
        self._services = AgentServices(
            workspace_path=workspace_path,
            ledger_sink=LedgerSink(workspace_path),
        )
        self._nodes = KnowledgeNodes(
            services=self._services,
            service=service,
            prefs=prefs,
            workspace_id=workspace_id,
        )

    @property
    def _ledger_sink(self):
        """Ledger sink used by standalone knowledge runs (``KnowledgeService.answer``)."""
        return self._services.ledger_sink

    @_ledger_sink.setter
    def _ledger_sink(self, sink) -> None:
        self._services.ledger_sink = sink

    def _add_retrieval_nodes(self, graph: StateGraph) -> None:
        """Add + wire the shared retrieval prefix: START → … → build_context.

        Reused by both ``build()`` (Ask/CLI/HTTP, retrieval + answering) and
        ``build_retrieval()`` (the chat subgraph, retrieval only) so the retrieval
        logic — including the history-aware ``rewrite_query`` node — has one implementation.
        """
        n = self._nodes
        graph.add_node("parse_query", n.parse_query_node)
        graph.add_node("rewrite_query", n.rewrite_query_node)
        graph.add_node("graph_expand", n.graph_expand_node)
        graph.add_node("graph_fetch", n.graph_fetch_node)
        graph.add_node("build_filters", n.build_filters_node)
        graph.add_node("embed_query", n.embed_query_node)
        graph.add_node("vector_search", n.vector_search_node)
        graph.add_node("rerank", n.rerank_node)
        graph.add_node("build_context", n.build_context_node)
        graph.add_edge(START, "parse_query")
        graph.add_edge("parse_query", "rewrite_query")
        # When rewrite decides the message needs no knowledge (small talk), skip straight to
        # build_context — bypassing build_filters / embed_query / vector_search. build_context
        # with no hits yields empty context + no_results, so downstream behaves like "no hits".
        graph.add_conditional_edges(
            "rewrite_query",
            KnowledgeNodes.route_after_rewrite,
            {"retrieve": "graph_expand", "skip": "build_context"},
        )
        # graph_expand runs unconditionally on the retrieve path; it short-circuits
        # internally when ``graph_mode=off`` (the default) or there's no query/graph.
        # Cost when off = ~zero. See ``graph_expand_node`` impl.
        graph.add_conditional_edges(
            "graph_expand",
            KnowledgeNodes.route_after_expand,
            {"graph_only": "graph_fetch", "vector": "build_filters"},
        )
        graph.add_edge("graph_fetch", "build_context")
        graph.add_edge("build_filters", "embed_query")
        graph.add_edge("embed_query", "vector_search")
        graph.add_edge("vector_search", "rerank")
        graph.add_edge("rerank", "build_context")

    def build(self) -> CompiledStateGraph:
        """Full Ask/CLI/HTTP graph: shared retrieval prefix + cited-answer step."""
        graph = StateGraph(KnowledgeAgentState)
        self._add_retrieval_nodes(graph)
        n = self._nodes
        graph.add_node("call_model", n.call_model_node)
        graph.add_node("finalize", n.finalize_node)
        graph.add_conditional_edges(
            "build_context",
            KnowledgeNodes.route_after_context,
            {"call_model": "call_model", "finalize": "finalize"},
        )
        graph.add_edge("call_model", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    def build_retrieval(self) -> CompiledStateGraph:
        """Retrieval-only subgraph for the chat agent: shared prefix → END.

        Compiled without a checkpointer (retrieval is per-turn scratch). It opens no ledger
        run of its own, so when invoked inside a chat run its node rows inherit the chat
        ``run_id`` and fold into that turn's cost (see ``ledger._resolve_ledger_identity``).
        """
        graph = StateGraph(KnowledgeAgentState)
        self._add_retrieval_nodes(graph)
        graph.add_edge("build_context", END)
        return graph.compile()
