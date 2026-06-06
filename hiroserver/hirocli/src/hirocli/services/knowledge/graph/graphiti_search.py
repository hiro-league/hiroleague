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

from graphiti_core.search.search_config import (
    EpisodeReranker,
    EpisodeSearchConfig,
    EpisodeSearchMethod,
    NodeReranker,
    NodeSearchConfig,
    NodeSearchMethod,
    SearchConfig,
)
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


# Map the user-facing recipe choice onto the Node/Episode reranker enums.
#   - Nodes support {rrf, mmr, cross_encoder} → identity-ish (same names exist).
#   - Episodes are BM25-only with only {rrf, cross_encoder}. ``mmr`` is rejected up-front
#     by ``GraphPreferences._validate_search_scope_recipe``; this map only handles the legal
#     combos that reach here.
_NODE_RERANKER = {
    "rrf": NodeReranker.rrf,
    "mmr": NodeReranker.mmr,
    "cross_encoder": NodeReranker.cross_encoder,
}
_EPISODE_RERANKER = {
    "rrf": EpisodeReranker.rrf,
    "cross_encoder": EpisodeReranker.cross_encoder,
}


def _build_search_config(
    recipe: str,
    *,
    num_results: int,
    k_hop: int,
    min_relevance: float,
    sim_min_score: float,
    scope: str = "edges",
) -> SearchConfig:
    """Clone the recipe and apply the admin knobs (no hardcoded params, repo rule).

    ``num_results`` → ``SearchConfig.limit`` (facts kept), ``k_hop`` →
    ``EdgeSearchConfig.bfs_max_depth`` (graph expansion radius), ``min_relevance`` →
    ``SearchConfig.reranker_min_score`` (drop low-relevance facts; meaningful only for
    the cross-encoder, whose scores are calibrated), ``sim_min_score`` →
    ``EdgeSearchConfig.sim_min_score`` (cosine *candidate* floor). Deep-copied so the
    shared module recipe constants are never mutated.

    Why ``sim_min_score`` matters: graphiti hardcodes ``EdgeSearchConfig.sim_min_score``
    to ``DEFAULT_MIN_SCORE = 0.6``, which is too strict for our embedder. A
    paraphrase-distant query (asking for a "wife" when the extracted fact says
    "married to") scores below 0.6, so the cosine leg returns ZERO candidates; if bm25
    also misses (the discriminating word isn't in the terse fact), the whole fact search
    comes back empty (facts_0/0) and the leg silently falls back to flat. Driving this
    from the pref keeps candidate generation recall-oriented; the reranker
    (``reranker_min_score``) is where precision belongs."""
    base = _EDGE_RECIPES.get(recipe, EDGE_HYBRID_SEARCH_RRF)
    config = base.model_copy(deep=True)
    config.limit = max(1, int(num_results))
    config.reranker_min_score = max(0.0, float(min_relevance))
    if config.edge_config is not None:
        config.edge_config.bfs_max_depth = max(1, int(k_hop))
        config.edge_config.sim_min_score = max(0.0, min(1.0, float(sim_min_score)))
    # Mount additional legs per scope. We keep the same recipe choice across legs so the
    # within-leg ranking is consistent — orthogonal axes (decision: search_scope × search_recipe
    # compose). Limits are shared via SearchConfig.limit; rerankers are per-leg.
    if scope in ("edges_and_nodes", "edges_nodes_episodes"):
        config.node_config = NodeSearchConfig(
            search_methods=[NodeSearchMethod.bm25, NodeSearchMethod.cosine_similarity],
            reranker=_NODE_RERANKER.get(recipe, NodeReranker.rrf),
            sim_min_score=max(0.0, min(1.0, float(sim_min_score))),
            bfs_max_depth=max(1, int(k_hop)),
        )
    if scope == "edges_nodes_episodes":
        # Episodes leg is BM25-only (graphiti-core). The MMR×episodes combo is rejected at
        # pref-validation; reaching here, ``recipe`` is rrf or cross_encoder → both safe.
        config.episode_config = EpisodeSearchConfig(
            search_methods=[EpisodeSearchMethod.bm25],
            reranker=_EPISODE_RERANKER.get(recipe, EpisodeReranker.rrf),
        )
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
    """Result of a Graphiti search, reduced to the retrieval focus set.

    ``chunk_ids`` is the union of supporting episode uuids (== Qdrant point_ids)
    across the kept facts — the focus set for hybrid+rerank. Empty ⇒ the graph
    couldn't anchor this query and the caller falls back to flat search.
    ``facts`` are the fact texts (for the ledger / future answer skeleton).
    ``ranked`` is the ordered fact list (incl. superseded, marked) for the ledger.

    ``node_memories`` / ``episode_memories`` are populated only when ``search_scope`` is
    widened beyond ``edges`` (decision: extends D3). Each is a short text the answer model
    can read as additional memory: node summaries are per-entity *attribute* memories (e.g.
    ``"About Misho: turned 50 years old in June 2026"``); episode memories are raw turn
    bodies recalled via BM25 — useful as last-resort recall, noisier than facts."""

    chunk_ids: tuple[str, ...]
    facts: tuple[str, ...]
    facts_total: int  # facts returned by search
    facts_used: int   # facts kept after the temporal filter
    ranked: tuple[RankedFact, ...] = ()
    node_memories: tuple[str, ...] = ()
    episode_memories: tuple[str, ...] = ()


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


def _fact_with_date(fact: str, valid_at: str, invalid_at: str) -> str:
    """Append the fact's temporal validity so the answer LLM can resolve relative
    dates in the episode body ("today", "next month") to an absolute date (G4).

    Without this the skeleton fact "Adam started a new job at Brightloom" reaches the
    model dateless and it cannot confirm month/year questions. ``valid_at → invalid_at``
    is shown when the fact has been superseded (temporal='all'); a current fact shows
    only its start. No dates ⇒ bare fact (graph never anchored a time)."""
    if valid_at and invalid_at:
        return f"{fact} (valid {valid_at} → {invalid_at})"
    if valid_at:
        return f"{fact} (as of {valid_at})"
    return fact


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
    sim_min_score: float = 0.3,
    scope: str = "edges",
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

    # Firm scoping (docs/graph-group-policy-design.md §6): a scoped read MUST name a
    # partition. Previously a falsy group_id became ``group_ids=None``, which tells graphiti
    # to search EVERY group — so knowledge search (whose group resolved to the empty default)
    # leaked conversation-memory facts from other users. There is no "search all" here: a
    # missing group fails SAFE to an empty expansion (caller soft-falls-back to flat search),
    # never to a cross-vertical scan.
    if not group_id:
        log.warning("⚠️ graphiti.search — missing group_id · returning empty (no all-groups scan)")
        return GraphitiExpansion((), (), 0, 0)

    # Push the current-only lens down to the query so superseded facts don't eat the
    # num_results budget (design §7). None ⇒ Graphiti applies its empty default filter.
    search_filter = _current_only_filter() if temporal == "current" else None
    config = _build_search_config(
        recipe,
        num_results=num_results,
        k_hop=k_hop,
        min_relevance=min_relevance,
        sim_min_score=sim_min_score,
        scope=scope,
    )
    try:
        results = await graphiti.search_(
            q,
            config=config,
            group_ids=[group_id],  # always scoped — never None/all-groups (see guard above)
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
        # Episode event time — resolve once; feeds both the ledger's RankedFact and the
        # dated answer-skeleton fact below (G4: the body's "today" needs an absolute date).
        valid_at = _iso(getattr(edge, "valid_at", None))
        invalid_at = _iso(getattr(edge, "invalid_at", None))
        episodes = [str(ep) for ep in (getattr(edge, "episodes", None) or []) if ep]
        # Ranked list keeps a bounded prefix incl. superseded (marked) for the ledger.
        if fact and len(ranked) < 8:
            ranked.append(
                RankedFact(
                    fact=fact,
                    valid_at=valid_at,
                    invalid_at=invalid_at,
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
            # Carry the date into the skeleton fact so the answer model can ground
            # relative phrasing in the supporting passage to an absolute date.
            facts.append(_fact_with_date(fact, valid_at, invalid_at))

    # Scope-widened legs — only populated when the recipe mounted them. ``SearchResults``
    # always has the fields (defaulted to ``[]``), so unmounted legs naturally return empty.
    node_memories: list[str] = []
    for node in getattr(results, "nodes", None) or []:
        summary = (getattr(node, "summary", "") or "").strip()
        if not summary:
            continue
        name = (getattr(node, "name", "") or "").strip()
        # Attribute-style memory: prefix with the entity name so the answer model can
        # attribute the statement back to its subject ("About Misho: …").
        node_memories.append(f"About {name}: {summary}" if name else summary)
    episode_memories: list[str] = []
    for ep in getattr(results, "episodes", None) or []:
        content = (getattr(ep, "content", "") or "").strip()
        if content:
            episode_memories.append(content)

    log.info(
        "⬇️ graphiti.search — facts=%d/%d nodes=%d episodes=%d chunks=%d scope=%s temporal=%s",
        used,
        len(edges),
        len(node_memories),
        len(episode_memories),
        len(chunk_ids),
        scope,
        temporal,
    )
    return GraphitiExpansion(
        chunk_ids=tuple(sorted(chunk_ids)),  # sorted → deterministic filter keys
        facts=tuple(facts),
        facts_total=len(edges),
        facts_used=used,
        ranked=tuple(ranked),
        node_memories=tuple(node_memories),
        episode_memories=tuple(episode_memories),
    )


__all__ = ["GraphitiExpansion", "RankedFact", "search_chunk_ids"]
