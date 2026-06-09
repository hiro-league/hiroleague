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

from .retrieval_trace import RetrievalTrace, StageRecord, current_capture

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
    # Edge metadata surfaced for the eval recalled-facts table (best-effort via getattr —
    # the production ``search_()`` edge always carries these; older fakes default to blank).
    name: str = ""           # relationship/edge type (e.g. WORKS_AT)
    source_uuid: str = ""    # subject entity uuid
    target_uuid: str = ""    # object entity uuid
    uuid: str = ""           # fact edge uuid
    score: float | None = None  # relevance score when the backend exposes it (else None)


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
    # Structured kept items (parallel to the ``*_memories`` strings) for the eval recalled-items
    # tables: each carries the display text + metadata + relevance score. ``fact_rows`` adds
    # temporal/source/relationship; ``node_rows`` adds entity name/type; ``episode_rows`` adds the
    # turn timestamp. All default to () so older fakes (and the agent's string-only path) work.
    fact_rows: tuple[dict[str, Any], ...] = ()
    node_rows: tuple[dict[str, Any], ...] = ()
    episode_rows: tuple[dict[str, Any], ...] = ()


def _node_entity_type(node: Any) -> str:
    """First non-base ontology label is the entity's type (e.g. ``Person``); else ``Entity``.

    Mirrors ``retrieval_trace._node_entity_type`` so the recall entity rows show the same type
    the trace dialog does (kept local to avoid importing the trace module on the hot path)."""
    for label in getattr(node, "labels", None) or []:
        if label and label != "Entity":
            return str(label)
    return "Entity"


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


async def _traced_search(
    graphiti: Any,
    query: str,
    *,
    group_id: str,
    config: SearchConfig,
    search_filter: SearchFilters | None,
    temporal: str,
    num_results: int,
    sim_min_score: float,
    k_hop: int,
    recipe: str,
) -> tuple[
    list[Any],
    list[Any],
    list[Any],
    dict[str, float | None],
    dict[str, float | None],
    dict[str, float | None],
]:
    """Run the re-hosted, per-stage-traced pipeline for every configured lane.

    Replaces ``graphiti.search_()`` WHEN a capture is active so we record each lane's
    candidate legs / hop / rank / temporal: the ``edge`` (fact) lane always, plus the
    ``node`` (entity) and ``episode`` lanes when the scope mounted their configs. Pinned
    to a known graphiti layout (``graphiti_compat``); the embed stage is recorded here
    (one shared query vector) since the embedder call is ours. Returns
    ``(edges, nodes, episodes)`` — the same triple ``graphiti.search_`` would produce."""
    # Lazy imports: only the capture path touches graphiti internals + the compat pin,
    # so the default production path never pays for them.
    from .graphiti_compat import assert_graphiti_compatible
    from .graphiti_fact_search import (
        search_episodes_traced,
        search_facts_traced,
        search_nodes_traced,
    )
    from .retrieval_trace import RetrievalCapture

    assert_graphiti_compatible()
    capture = current_capture.get()
    if capture is None:  # defensive — only called when a capture is active
        capture = RetrievalCapture()

    clients = graphiti.clients
    trace = RetrievalTrace(
        query=query,
        group_id=group_id,
        recipe=recipe,
        temporal=temporal,
        num_results=num_results,
        sim_min_score=sim_min_score,
        k_hop=k_hop,
    )
    sf = search_filter if search_filter is not None else SearchFilters()

    import time as _time

    started = _time.perf_counter()
    query_vector = await clients.embedder.create(input_data=[query.replace("\n", " ")])
    trace.add_stage(
        StageRecord(
            kind="embed",
            label="Embed query",
            lane="query",
            elapsed_ms=(_time.perf_counter() - started) * 1000.0,
            meta={"query_length": len(query), "vector_dim": len(query_vector)},
        )
    )

    # Edge (fact) lane — always present. ``edge_scores`` (uuid→rerank score) is threaded back so
    # recall fact rows can show the same score the trace does (graphiti leaves edge.score unset).
    edges, edge_scores = await search_facts_traced(
        clients,
        query,
        query_vector,
        group_ids=[group_id],
        edge_config=config.edge_config,
        search_filter=sf,
        limit=config.limit,
        reranker_min_score=config.reranker_min_score,
        capture=capture,
        trace=trace,
    )

    # Node (entity) lane — only when the scope mounted a node_config. ``node_scores`` (uuid→rerank
    # score) is threaded back so recall entity rows can show the same score the trace does.
    nodes: list[Any] = []
    node_scores: dict[str, float | None] = {}
    if getattr(config, "node_config", None) is not None:
        nodes, node_scores = await search_nodes_traced(
            clients,
            query,
            query_vector,
            group_ids=[group_id],
            node_config=config.node_config,
            search_filter=sf,
            limit=config.limit,
            reranker_min_score=config.reranker_min_score,
            trace=trace,
        )

    # Episode lane — only when the scope mounted an episode_config. ``episode_scores`` threaded
    # back for the same reason as the node lane.
    episodes: list[Any] = []
    episode_scores: dict[str, float | None] = {}
    if getattr(config, "episode_config", None) is not None:
        episodes, episode_scores = await search_episodes_traced(
            clients,
            query,
            group_ids=[group_id],
            episode_config=config.episode_config,
            search_filter=sf,
            limit=config.limit,
            reranker_min_score=config.reranker_min_score,
            trace=trace,
        )

    capture.trace = trace
    return edges, nodes, episodes, edge_scores, node_scores, episode_scores


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
    # When a retrieval capture is active (eval / Graph-Runs inspection), route ALL
    # configured lanes (edge always; node/episode when the scope mounts them) through the
    # re-hosted, per-stage-traced pipeline so we record candidate legs / hop / rank /
    # temporal. With no capture we keep the stock ``search_()`` production path untouched
    # (test fakes that only expose ``search_`` never set a capture, so they're unaffected).
    capture = current_capture.get()
    use_trace = capture is not None
    nodes_result: list[Any] = []
    episodes_result: list[Any] = []
    # uuid→rerank score from the traced fact pipeline (empty on the stock ``search_`` path);
    # the fact loop prefers this over edge.score, which graphiti leaves unset. The node/episode
    # lanes get the same treatment so the recall entity/episode rows can show a real score.
    edge_scores: dict[str, float | None] = {}
    node_scores: dict[str, float | None] = {}
    episode_scores: dict[str, float | None] = {}
    try:
        if use_trace:
            (
                edges,
                nodes_result,
                episodes_result,
                edge_scores,
                node_scores,
                episode_scores,
            ) = await _traced_search(
                graphiti,
                q,
                group_id=group_id,
                config=config,
                search_filter=search_filter,
                temporal=temporal,
                num_results=num_results,
                sim_min_score=sim_min_score,
                k_hop=k_hop,
                recipe=recipe,
            )
        else:
            results = await graphiti.search_(
                q,
                config=config,
                group_ids=[group_id],  # always scoped — never None/all-groups (see guard above)
                search_filter=search_filter,
            )
            edges = getattr(results, "edges", None) or []
            nodes_result = getattr(results, "nodes", None) or []
            episodes_result = getattr(results, "episodes", None) or []
    except Exception:
        # External model + DB call — log + re-raise (caller soft-falls-back to flat).
        log.warning("❌ graphiti.search_ — failed · q=%r recipe=%s", q[:80], recipe, exc_info=True)
        raise

    chunk_ids: set[str] = set()
    facts: list[str] = []
    fact_rows: list[dict[str, Any]] = []
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
        # Edge metadata for the recalled-facts table (best-effort; blank when absent).
        name = (getattr(edge, "name", "") or "").strip()
        source_uuid = str(getattr(edge, "source_node_uuid", "") or "")
        target_uuid = str(getattr(edge, "target_node_uuid", "") or "")
        edge_uuid = str(getattr(edge, "uuid", "") or "")
        # Prefer the threaded rerank score (traced path) — graphiti never writes it back onto
        # the edge, so the recalled-facts Score column was always blank. Fall back to edge.score
        # for the stock path (where it stays None today, but keep the read for forward-compat).
        raw_score = edge_scores.get(edge_uuid, getattr(edge, "score", None))
        score = float(raw_score) if isinstance(raw_score, (int, float)) else None
        # Ranked list keeps a bounded prefix incl. superseded (marked) for the ledger.
        if fact and len(ranked) < 8:
            ranked.append(
                RankedFact(
                    fact=fact,
                    valid_at=valid_at,
                    invalid_at=invalid_at,
                    chunk_id=episodes[0] if episodes else "",
                    superseded=superseded,
                    name=name,
                    source_uuid=source_uuid,
                    target_uuid=target_uuid,
                    uuid=edge_uuid,
                    score=score,
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
            dated = _fact_with_date(fact, valid_at, invalid_at)
            facts.append(dated)
            # Parallel structured row (the recalled-facts table reads these).
            fact_rows.append(
                {
                    "kind": "fact",
                    "memory": dated,
                    "fact": fact,
                    "valid_at": valid_at,
                    "invalid_at": invalid_at,
                    "superseded": superseded,
                    "chunk_id": episodes[0] if episodes else "",
                    "name": name,
                    "source_uuid": source_uuid,
                    "target_uuid": target_uuid,
                    "uuid": edge_uuid,
                    "score": score,
                }
            )

    # Scope-widened legs — only populated when the recipe mounted them. ``SearchResults``
    # always has the fields (defaulted to ``[]``), so unmounted legs naturally return empty.
    # ``*_memories`` stay plain strings (the agent memory_block reads them); the parallel
    # ``*_rows`` carry score + metadata for the eval recalled-items tables (mirrors fact_rows).
    node_memories: list[str] = []
    node_rows: list[dict[str, Any]] = []
    for node in nodes_result:
        summary = (getattr(node, "summary", "") or "").strip()
        if not summary:
            continue
        name = (getattr(node, "name", "") or "").strip()
        # Attribute-style memory: prefix with the entity name so the answer model can
        # attribute the statement back to its subject ("About Misho: …").
        memory_text = f"About {name}: {summary}" if name else summary
        node_memories.append(memory_text)
        node_uuid = str(getattr(node, "uuid", "") or "")
        raw_score = node_scores.get(node_uuid, getattr(node, "score", None))
        node_rows.append(
            {
                "kind": "entity",
                "memory": memory_text,
                "name": name,
                "summary": summary,
                "entity_type": _node_entity_type(node),
                "uuid": node_uuid,
                "score": float(raw_score) if isinstance(raw_score, (int, float)) else None,
            }
        )
    episode_memories: list[str] = []
    episode_rows: list[dict[str, Any]] = []
    for ep in episodes_result:
        content = (getattr(ep, "content", "") or "").strip()
        if not content:
            continue
        episode_memories.append(content)
        ep_uuid = str(getattr(ep, "uuid", "") or "")
        raw_score = episode_scores.get(ep_uuid, getattr(ep, "score", None))
        episode_rows.append(
            {
                "kind": "episode",
                "memory": content,
                "valid_at": _iso(getattr(ep, "valid_at", None)),
                "uuid": ep_uuid,
                "score": float(raw_score) if isinstance(raw_score, (int, float)) else None,
            }
        )

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
        fact_rows=tuple(fact_rows),
        node_rows=tuple(node_rows),
        episode_rows=tuple(episode_rows),
    )


__all__ = ["GraphitiExpansion", "RankedFact", "search_chunk_ids"]
