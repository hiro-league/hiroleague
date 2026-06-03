"""Graphiti retrieval — query → fact edges → focused Qdrant chunk_ids.

The read half of the pivot (decision G4/G5, docs/knowledge-graphiti-pivot-design.md
§7). Graphiti ``search()`` returns fact edges (``EntityEdge``); each fact natively
carries the ``episodes`` that support it — and because we ingest with
``uuid = point_id``, those episode uuids **are** the Qdrant chunk_ids. So one
Graphiti search yields the focused chunk set the existing hybrid+rerank runs over
(``build_filters`` folds them into a ``HasIdCondition`` — unchanged wiring).

Temporal lens (design §7): Graphiti's default search is relevance-first, NOT
current-only. For ``temporal='current'`` we **push the filter down to the query**
via ``SearchFilters`` (``invalid_at IS NULL AND expired_at IS NULL``) so the
``num_results`` budget is spent on current facts — a relevance-similar superseded
fact ("lived in Boston") can no longer crowd the current one ("lives in Cambridge")
out of the top-N and then get discarded, leaving the answer empty. ``all`` keeps
history. A light Python drop of superseded facts is retained **only as
defense-in-depth** (the push-down is the real fix; the post-drop is a no-op once the
query filter applies, and still marks history in ``all`` mode for the ledger).

Engine-agnostic: takes the Graphiti client as an argument, so it is unit-testable
with a fake (no Kuzu, no model). ``SearchFilters`` is a pure pydantic model — its
import pulls in no engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from graphiti_core.search.search_config import SearchConfig
from graphiti_core.search.search_config_recipes import (
    EDGE_HYBRID_SEARCH_CROSS_ENCODER,
    EDGE_HYBRID_SEARCH_MMR,
    EDGE_HYBRID_SEARCH_RRF,
)
from graphiti_core.search.search_filters import (
    ComparisonOperator,
    DateFilter,
    SearchFilters,
)
from hiro_commons.log import Logger

log = Logger.get("SVC.KNOWLEDGE.GRAPH.GRAPHITI.SEARCH")

# search_recipe (admin pref) → Graphiti edge-search recipe. ``cross_encoder`` reranks
# with the model wired at construction (HiroRerankerCrossEncoder); ``rrf``/``mmr`` are
# fusion-only (no model). All are EDGE-only configs (we search facts, not nodes).
_EDGE_RECIPES: dict[str, SearchConfig] = {
    "rrf": EDGE_HYBRID_SEARCH_RRF,
    "mmr": EDGE_HYBRID_SEARCH_MMR,
    "cross_encoder": EDGE_HYBRID_SEARCH_CROSS_ENCODER,
}


def _build_search_config(
    recipe: str, *, num_results: int, k_hop: int, min_relevance: float
) -> SearchConfig:
    """Clone the recipe and apply the admin knobs (no hardcoded params, repo rule).

    ``num_results`` → ``SearchConfig.limit`` (facts kept), ``k_hop`` →
    ``EdgeSearchConfig.bfs_max_depth`` (graph expansion radius), ``min_relevance`` →
    ``SearchConfig.reranker_min_score`` (drop low-relevance facts; meaningful only for
    the cross-encoder, whose scores are calibrated). Deep-copied so the shared module
    recipe constants are never mutated."""
    base = _EDGE_RECIPES.get(recipe, EDGE_HYBRID_SEARCH_RRF)
    config = base.model_copy(deep=True)
    config.limit = max(1, int(num_results))
    config.reranker_min_score = max(0.0, float(min_relevance))
    if config.edge_config is not None:
        config.edge_config.bfs_max_depth = max(1, int(k_hop))
    return config


def _current_only_filter() -> SearchFilters:
    """Query-level 'current facts only' lens (design §7 — fixes the temporal gap).

    A current fact has NOT been invalidated or expired: ``invalid_at IS NULL AND
    expired_at IS NULL``. Pushing this into the search (vs. dropping superseded
    facts in Python afterwards) is the correctness fix: the post-drop approach let
    superseded facts consume the relevance-ranked ``num_results`` budget and then
    threw them away, so a current fact ranked just past the cut was never returned.
    The two fields are ANDed by Graphiti; each is a single OR-group / AND-clause."""
    is_null = DateFilter(comparison_operator=ComparisonOperator.is_null)
    return SearchFilters(invalid_at=[[is_null]], expired_at=[[is_null]])


@dataclass(frozen=True)
class RankedFact:
    """One fact edge in ranked order — for the Graph-Runs ``rerank`` node preview.

    ``superseded`` marks a fact dropped by the ``current`` temporal lens (so the
    ledger can show *why* it was excluded). See docs §12.2.2."""

    fact: str
    valid_at: str = ""
    invalid_at: str = ""
    chunk_id: str = ""
    superseded: bool = False


@dataclass(frozen=True)
class GraphitiExpansion:
    """Result of a Graphiti fact search, reduced to the retrieval focus set.

    ``chunk_ids`` is the union of supporting episode uuids (== Qdrant point_ids)
    across the kept facts — the focus set for hybrid+rerank. Empty ⇒ the graph
    couldn't anchor this query and the caller falls back to flat search.
    ``facts`` are the fact texts (for the ledger / future answer skeleton).
    ``ranked`` is the ordered fact list (incl. superseded, marked) for the ledger."""

    chunk_ids: tuple[str, ...]
    facts: tuple[str, ...]
    facts_total: int  # facts returned by search
    facts_used: int   # facts kept after the temporal filter
    ranked: tuple[RankedFact, ...] = ()


def _is_superseded(edge: Any) -> bool:
    """A fact is superseded when it has been invalidated or expired (temporal)."""
    return (
        getattr(edge, "expired_at", None) is not None
        or getattr(edge, "invalid_at", None) is not None
    )


def _iso(value: Any) -> str:
    """Best-effort ISO date string for a temporal field (``valid_at``/``invalid_at``)."""
    if value is None:
        return ""
    try:
        return value.date().isoformat()
    except Exception:
        return str(value)[:10]


async def search_chunk_ids(
    graphiti: Any,
    query: str,
    *,
    group_id: str | None = None,
    num_results: int = 20,
    temporal: str = "current",
    recipe: str = "rrf",
    k_hop: int = 1,
    min_relevance: float = 0.0,
) -> GraphitiExpansion:
    """Run Graphiti fact search → focused chunk_ids (+ fact texts).

    ``graphiti`` is anything exposing an async ``search_(query, config, group_ids,
    search_filter) -> SearchResults`` (the staged API — needed so ``recipe`` /
    ``k_hop`` / ``min_relevance`` actually take effect; the basic ``search()`` hardwires
    RRF + depth). ``temporal='current'`` pushes a current-only ``SearchFilters`` into
    the query (and a defensive Python drop); ``'all'`` keeps history. Empty/blank query
    → empty expansion (no-op)."""
    q = (query or "").strip()
    if not q:
        return GraphitiExpansion((), (), 0, 0)

    # Push the current-only lens down to the query so superseded facts don't eat the
    # num_results budget (design §7). None ⇒ Graphiti applies its empty default filter.
    search_filter = _current_only_filter() if temporal == "current" else None
    config = _build_search_config(
        recipe, num_results=num_results, k_hop=k_hop, min_relevance=min_relevance
    )
    try:
        results = await graphiti.search_(
            q,
            config=config,
            group_ids=[group_id] if group_id else None,
            search_filter=search_filter,
        )
    except Exception:
        # External model + DB call — log + re-raise (caller soft-falls-back to flat).
        log.warning("❌ graphiti.search_ — failed · q=%r recipe=%s", q[:80], recipe, exc_info=True)
        raise

    edges = getattr(results, "edges", None) or []
    chunk_ids: set[str] = set()
    facts: list[str] = []
    ranked: list[RankedFact] = []
    used = 0
    for edge in edges:
        superseded = _is_superseded(edge)
        fact = getattr(edge, "fact", "") or ""
        episodes = [str(ep) for ep in (getattr(edge, "episodes", None) or []) if ep]
        # Ranked list keeps a bounded prefix incl. superseded (marked) for the ledger.
        if fact and len(ranked) < 8:
            ranked.append(
                RankedFact(
                    fact=fact,
                    valid_at=_iso(getattr(edge, "valid_at", None)),
                    invalid_at=_iso(getattr(edge, "invalid_at", None)),
                    chunk_id=episodes[0] if episodes else "",
                    superseded=superseded,
                )
            )
        # Defense-in-depth only: the query-level SearchFilters already excludes these
        # for temporal=current, so this normally drops nothing (design §7).
        if temporal == "current" and superseded:
            continue
        used += 1
        for ep in episodes:
            chunk_ids.add(ep)
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
        ranked=tuple(ranked),
    )


__all__ = ["GraphitiExpansion", "RankedFact", "search_chunk_ids"]
