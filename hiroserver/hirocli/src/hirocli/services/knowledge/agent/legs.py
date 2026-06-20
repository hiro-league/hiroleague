"""Retrieval legs — the single source of truth for flat vs graphiti.

The leg is resolved in two steps: the *intended* leg (from the per-query graph_mode) gates
whether the graph is even consulted; the *effective* leg (after graph_expand) encodes the
soft-fallback (graphiti that found no supporting chunks behaves as flat). Downstream nodes read
the effective leg instead of re-deriving graph_mode + chunk_ids.
"""
from __future__ import annotations

from enum import Enum


class RetrievalLeg(str, Enum):  # str-Enum → JSON-safe in KnowledgeAgentState
    FLAT = "flat"
    GRAPHITI = "graphiti"


def intended_leg(graph_mode: str | None) -> RetrievalLeg:
    return RetrievalLeg.GRAPHITI if (graph_mode or "off") == "graphiti" else RetrievalLeg.FLAT


def effective_leg(intended: RetrievalLeg, *, chunk_ids: list) -> RetrievalLeg:
    """Soft-fallback made explicit: graphiti with no supporting chunks → flat."""
    if intended is RetrievalLeg.GRAPHITI and chunk_ids:
        return RetrievalLeg.GRAPHITI
    return RetrievalLeg.FLAT


def graphiti_facts_block(facts: list[str]) -> str:
    """The graph-leg answer skeleton prefix (moved verbatim out of build_context)."""
    kept = [f for f in (facts or []) if (f or "").strip()]
    if not kept:
        return ""
    return "Known facts from the knowledge graph:\n" + "\n".join(f"- {f}" for f in kept)
