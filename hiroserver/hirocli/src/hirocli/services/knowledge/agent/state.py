"""State schema for the knowledge retrieval / answering graph."""

from __future__ import annotations

from typing import Any, TypedDict

from hirocli.services.knowledge.agent.helpers import NormalizedQuery

# Runtime import (NOT TYPE_CHECKING): ``KnowledgeAgentState`` is a LangGraph ``StateGraph``
# schema; LangGraph evaluates its annotations via ``get_type_hints`` at build time, so these
# names must resolve at runtime despite ``from __future__ import annotations``.
from hirocli.services.knowledge.models import KnowledgeSearchHit, KnowledgeSource


class KnowledgeAgentState(TypedDict, total=False):
    """Per-invoke scratch for the knowledge retrieval / answering graph.

    Compiled without a checkpointer (``build_retrieval()``) or with ephemeral runs only —
    no cross-call persistence. Every field is written during a single invocation and may be
    absent at entry.
    """

    # --- Query in ---
    query: str
    filters: dict[str, Any]
    top_k: int
    min_score: float
    explain: bool
    rewrite: bool
    graph_mode: str
    graph_temporal: str
    history: str

    # --- Rewrite output ---
    rewrite_keywords: list[str]
    knowledge_needed: bool
    rewritten_query: str | None
    normalized_query: NormalizedQuery
    query_entities: list[str]

    # --- Graph leg (graphiti) ---
    graph_facts: list[str]
    graph_chunk_ids: list[str]
    # Set by graph_expand: the resolved leg after the soft-fallback. Downstream nodes read THIS,
    # not graph_mode + chunk_ids. Values: RetrievalLeg.value ("flat" | "graphiti").
    effective_leg: str

    # --- Vector leg ---
    qdrant_filter: Any
    query_vector: list[float]
    query_sparse_vector: Any
    hits: list[KnowledgeSearchHit]
    reranked: bool

    # --- Assembly / answer ---
    sources: list[KnowledgeSource]
    context: str
    answer: str
    model_id: str | None
    usage: dict[str, Any]
    no_results: bool

    # --- Identity / bookkeeping ---
    started_at: str
    elapsed_ms: int
    inbound_id: str
    chat_channel_id: int | str
    device_id: str
    user_id: str
    character_id: str
