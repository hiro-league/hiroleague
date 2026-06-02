"""Graphiti retrieval — query → fact edges → focused Qdrant chunk_ids.

The read half of the pivot (decision G4/G5, docs/knowledge-graphiti-pivot-design.md
§7). Graphiti ``search()`` returns fact edges (``EntityEdge``); each fact natively
carries the ``episodes`` that support it — and because we ingest with
``uuid = point_id``, those episode uuids **are** the Qdrant chunk_ids. So one
Graphiti search yields the focused chunk set the existing hybrid+rerank runs over
(``build_filters`` folds them into a ``HasIdCondition`` — unchanged wiring).

Temporal lens: Graphiti's default search is relevance-first, NOT current-only. We
apply the ``current`` filter in Python (drop facts with ``invalid_at``/``expired_at``
set) so a superseded fact ("lived in Boston") doesn't leak when the user asks for
the present. ``all`` keeps history.

Engine-agnostic: takes the Graphiti client as an argument, so it is unit-testable
with a fake (no Kuzu, no model).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hiro_commons.log import Logger

log = Logger.get("SVC.KNOWLEDGE.GRAPH.GRAPHITI.SEARCH")


@dataclass(frozen=True)
class GraphitiExpansion:
    """Result of a Graphiti fact search, reduced to the retrieval focus set.

    ``chunk_ids`` is the union of supporting episode uuids (== Qdrant point_ids)
    across the kept facts — the focus set for hybrid+rerank. Empty ⇒ the graph
    couldn't anchor this query and the caller falls back to flat search.
    ``facts`` are the fact texts (for the ledger / future answer skeleton)."""

    chunk_ids: tuple[str, ...]
    facts: tuple[str, ...]
    facts_total: int  # facts returned by search
    facts_used: int   # facts kept after the temporal filter


def _is_superseded(edge: Any) -> bool:
    """A fact is superseded when it has been invalidated or expired (temporal)."""
    return (
        getattr(edge, "expired_at", None) is not None
        or getattr(edge, "invalid_at", None) is not None
    )


async def search_chunk_ids(
    graphiti: Any,
    query: str,
    *,
    group_id: str | None = None,
    num_results: int = 20,
    temporal: str = "current",
) -> GraphitiExpansion:
    """Run Graphiti fact search → focused chunk_ids (+ fact texts).

    ``graphiti`` is anything exposing an async ``search(query, group_ids,
    num_results) -> list[edge]``. ``temporal='current'`` drops superseded facts;
    ``'all'`` keeps them. Empty/blank query → empty expansion (no-op)."""
    q = (query or "").strip()
    if not q:
        return GraphitiExpansion((), (), 0, 0)

    try:
        edges = await graphiti.search(
            q,
            group_ids=[group_id] if group_id else None,
            num_results=num_results,
        )
    except Exception:
        # External model + DB call — log + re-raise (caller soft-falls-back to flat).
        log.warning("❌ graphiti.search — failed · q=%r", q[:80], exc_info=True)
        raise

    edges = edges or []
    chunk_ids: set[str] = set()
    facts: list[str] = []
    used = 0
    for edge in edges:
        if temporal == "current" and _is_superseded(edge):
            continue
        used += 1
        for ep in getattr(edge, "episodes", None) or []:
            if ep:
                chunk_ids.add(str(ep))
        fact = getattr(edge, "fact", "") or ""
        if fact:
            facts.append(fact)

    log.info(
        "⬇️ graphiti.search — facts=%d/%d chunks=%d temporal=%s",
        used,
        len(edges),
        len(chunk_ids),
        temporal,
    )
    return GraphitiExpansion(
        chunk_ids=tuple(sorted(chunk_ids)),  # sorted → deterministic filter keys
        facts=tuple(facts),
        facts_total=len(edges),
        facts_used=used,
    )


__all__ = ["GraphitiExpansion", "search_chunk_ids"]
