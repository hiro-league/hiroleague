"""LangGraph builder for admin knowledge retrieval and answering.

Mirrors ``runtime.agent_graph.chat.ChatAgentGraph``: a long-lived ``AgentServices`` is
supplied at construction, and per-flow inputs (retrieval engine, prefs snapshot,
workspace id) are passed to ``build``/``build_retrieval`` as a ``KnowledgeGraphConfig``.

Two cohesive groups (review §1.6):

- ``KnowledgeRetrievalNodes`` — 9-node retrieval pipeline + the two retrieval-side routers
- ``KnowledgeAnswerNodes`` — call_model + finalize + the post-context router

The retrieval-only subgraph (``build_retrieval``) mounts ONLY the retrieval group; the full
Ask/CLI/HTTP graph mounts both. Source order in each group's module is the registration
order, so no ``_NODE_REGISTRATION_ORDER`` classvar is needed.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from hirocli.runtime.agent_graph.node_group import mount as _mount
from hirocli.runtime.agent_graph.services import AgentServices

from .answer_nodes import KnowledgeAnswerNodes
from .config import KnowledgeGraphConfig
from .retrieval_nodes import KnowledgeRetrievalNodes
from .state import KnowledgeAgentState


def _wire_retrieval_prefix(graph: StateGraph) -> None:
    """Wire the shared retrieval prefix: START → … → build_context.

    Reused by both ``build()`` (Ask/CLI/HTTP, retrieval + answering) and ``build_retrieval()``
    (the chat subgraph, retrieval only) so the history-aware rewrite + soft graph/vector
    fallback have exactly one wiring.
    """
    graph.add_edge(START, "parse_query")
    graph.add_edge("parse_query", "rewrite_query")
    # When rewrite decides the message needs no knowledge (small talk), skip straight to
    # build_context — bypassing build_filters / embed_query / vector_search. build_context
    # with no hits yields empty context + no_results, so downstream behaves like "no hits".
    graph.add_conditional_edges(
        "rewrite_query",
        KnowledgeRetrievalNodes.route_after_rewrite,
        {"retrieve": "graph_expand", "skip": "build_context"},
    )
    # graph_expand runs unconditionally on the retrieve path; it short-circuits internally
    # when ``graph_mode=off`` (the default) or there's no query/graph. Cost when off = ~zero.
    graph.add_conditional_edges(
        "graph_expand",
        KnowledgeRetrievalNodes.route_after_expand,
        {"graph_only": "graph_fetch", "vector": "build_filters"},
    )
    graph.add_edge("graph_fetch", "build_context")
    graph.add_edge("build_filters", "embed_query")
    graph.add_edge("embed_query", "vector_search")
    graph.add_edge("vector_search", "rerank")
    graph.add_edge("rerank", "build_context")


class KnowledgeAgentGraph:
    """Builder that composes ``KnowledgeRetrievalNodes`` + ``KnowledgeAnswerNodes``.

    ``__init__`` takes the shared ``AgentServices`` (workspace path + ledger sink + checkpointer).
    ``build`` / ``build_retrieval`` take a per-build ``KnowledgeGraphConfig`` carrying the
    retrieval engine, prefs snapshot, and workspace id.
    """

    def __init__(self, services: AgentServices) -> None:
        self._services = services

    @property
    def services(self) -> AgentServices:
        return self._services

    @property
    def _ledger_sink(self):
        """Ledger sink used by standalone knowledge runs (``KnowledgeService.answer``)."""
        return self._services.ledger_sink

    @_ledger_sink.setter
    def _ledger_sink(self, sink) -> None:
        self._services.ledger_sink = sink

    def build(self, config: KnowledgeGraphConfig) -> CompiledStateGraph:
        """Full Ask/CLI/HTTP graph: shared retrieval prefix + cited-answer step."""
        retrieval = KnowledgeRetrievalNodes(self._services, config)
        answer = KnowledgeAnswerNodes(self._services, config)
        graph = StateGraph(KnowledgeAgentState)
        _mount(graph, retrieval)
        _mount(graph, answer)
        _wire_retrieval_prefix(graph)
        graph.add_conditional_edges(
            "build_context",
            KnowledgeAnswerNodes.route_after_context,
            {"call_model": "call_model", "finalize": "finalize"},
        )
        graph.add_edge("call_model", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    def build_retrieval(self, config: KnowledgeGraphConfig) -> CompiledStateGraph:
        """Retrieval-only subgraph for the chat agent: shared prefix → END.

        Compiled without a checkpointer (retrieval is per-turn scratch). It opens no ledger
        run of its own, so when invoked inside a chat run its node rows inherit the chat
        ``run_id`` and fold into that turn's cost (see ``ledger._resolve_ledger_identity``).
        """
        retrieval = KnowledgeRetrievalNodes(self._services, config)
        graph = StateGraph(KnowledgeAgentState)
        _mount(graph, retrieval)
        _wire_retrieval_prefix(graph)
        graph.add_edge("build_context", END)
        return graph.compile()
