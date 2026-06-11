"""Re-hosted Graphiti fact (edge) search with full per-stage trace capture.

This re-implements graphiti-core's ``search.edge_search`` orchestration so we can
record the data flowing **in and out of every stage** — both candidate legs, BFS hop
expansion, ranking (rrf / mmr / cross-encoder), and the temporal lens — which the
stock ``search()`` computes in local variables and throws away (it exposes only
counts via spans and the final reranked list via ``SearchResults``).

It is engaged **only when a capture is active** (``retrieval_trace.current_capture``)
and only for the **edges** scope; otherwise the service uses the stock
``graphiti.search_()`` so the production path is unchanged. The replicated logic is
pinned to a known graphiti-core layout by :mod:`graphiti_compat` and guarded by a
parity test, so any upstream drift fails loud (no-backward-compatibility rule).

Faithful to graphiti 0.29.1 ``edge_search``: each leg pulls ``2 * limit`` candidates;
when the ``bfs`` method is configured with no explicit origins, a second BFS pass
expands from the candidate legs' source nodes; the cross-encoder only ranks the first
``limit`` unique candidates **in insertion order** (bm25 → cosine → bfs)."""

from __future__ import annotations

import time
from typing import Any

from graphiti_core.search.search_config import (
    EdgeReranker,
    EdgeSearchMethod,
    EpisodeReranker,
    NodeReranker,
    NodeSearchMethod,
)
from graphiti_core.search.search_utils import (
    edge_fulltext_search,
    edge_similarity_search,
    episode_fulltext_search,
    get_embeddings_for_edges,
    get_embeddings_for_nodes,
    maximal_marginal_relevance,
    node_fulltext_search,
    node_similarity_search,
    rrf,
)
from hiro_commons.log import Logger

# BFS legs come from our SHORTEST-path rewrite, NOT graphiti's search_utils: the
# vendored Kuzu fallbacks enumerate all paths up to the hop bound (~degree^depth
# through hubs) and exhausted the Kuzu buffer pool at k_hop=3 on the LoCoMo eval.
# Aliased to the vendored names so the call sites and trace labels stay identical;
# result sets are proven equal by test_graphiti_bfs.py parity tests.
from .graphiti_bfs import (
    edge_bfs_search_shortest as edge_bfs_search,
    node_bfs_search_shortest as node_bfs_search,
)

from .retrieval_trace import (
    RetrievalCapture,
    RetrievalTrace,
    StageRecord,
    _edge_brief,
    _episode_brief,
    _node_brief,
)

log = Logger.get("SVC.KNOWLEDGE.GRAPH.FACT_SEARCH")


def _is_superseded(edge: Any) -> bool:
    return (
        getattr(edge, "expired_at", None) is not None
        or getattr(edge, "invalid_at", None) is not None
    )


async def search_facts_traced(
    clients: Any,
    query: str,
    query_vector: list[float],
    *,
    group_ids: list[str] | None,
    edge_config: Any,
    search_filter: Any,
    limit: int,
    reranker_min_score: float,
    capture: RetrievalCapture,
    trace: RetrievalTrace,
) -> tuple[list[Any], dict[str, float | None]]:
    """Run the edge pipeline, recording each stage into ``trace``; return reranked edges
    AND their uuid→rerank-score map.

    The score map is returned because graphiti never writes the rerank score back onto the
    edge objects — so the caller can surface the same score the trace shows onto the recall
    fact rows (the eval recalled-facts Score column was always blank without it).

    Mirrors ``graphiti_core.search.search.edge_search`` for the rerankers our recipes
    use (rrf / mmr / cross_encoder). ``query_vector`` is the already-embedded query
    (the embed stage is recorded by the caller, which owns the embedder call)."""
    driver = clients.driver
    cross_encoder = clients.cross_encoder
    candidate_limit = 2 * limit
    methods = list(edge_config.search_methods)

    # --- Candidate legs (parallel in graphiti; sequential here so each leg's output is
    # attributable to its method for the trace — same queries, same 2*limit fanout). ---
    search_results: list[list[Any]] = []
    leg_labels: list[str] = []
    if EdgeSearchMethod.bm25 in methods:
        started = time.perf_counter()
        bm25 = await edge_fulltext_search(driver, query, search_filter, group_ids, candidate_limit)
        trace.add_stage(
            StageRecord(
                kind="candidate",
                label="Keyword leg · BM25",
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                meta={"method": "bm25", "candidate_limit": candidate_limit, "count": len(bm25)},
                items=[_edge_brief(e) for e in bm25],
            )
        )
        search_results.append(bm25)
        leg_labels.append("bm25")
    if EdgeSearchMethod.cosine_similarity in methods:
        started = time.perf_counter()
        cosine = await edge_similarity_search(
            driver,
            query_vector,
            None,
            None,
            search_filter,
            group_ids,
            candidate_limit,
            getattr(edge_config, "sim_min_score", 0.0),
        )
        trace.add_stage(
            StageRecord(
                kind="candidate",
                label="Meaning leg · cosine",
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                meta={
                    "method": "cosine_similarity",
                    "candidate_limit": candidate_limit,
                    "sim_min_score": float(getattr(edge_config, "sim_min_score", 0.0)),
                    "count": len(cosine),
                },
                items=[_edge_brief(e) for e in cosine],
            )
        )
        search_results.append(cosine)
        leg_labels.append("cosine_similarity")
    if EdgeSearchMethod.bfs in methods:
        # Configured-origin BFS leg (no explicit origins from us ⇒ returns []); the real
        # expansion is the auto-expand pass below. Recorded for fidelity.
        started = time.perf_counter()
        bfs_leg = await edge_bfs_search(
            driver, None, edge_config.bfs_max_depth, search_filter, group_ids, candidate_limit
        )
        trace.add_stage(
            StageRecord(
                kind="candidate",
                label="BFS leg (explicit origins)",
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                meta={"method": "bfs", "candidate_limit": candidate_limit, "count": len(bfs_leg)},
                items=[_edge_brief(e) for e in bfs_leg],
            )
        )
        search_results.append(bfs_leg)
        leg_labels.append("bfs")

    # --- Hop expansion: BFS outward from the candidate legs' source nodes (graphiti's
    # auto-expand when bfs is configured with no explicit origins). ---
    if EdgeSearchMethod.bfs in methods:
        origins = [edge.source_node_uuid for result in search_results for edge in result]
        started = time.perf_counter()
        expanded = await edge_bfs_search(
            driver, origins, edge_config.bfs_max_depth, search_filter, group_ids, candidate_limit
        )
        trace.add_stage(
            StageRecord(
                kind="hop",
                label="Hop expansion · BFS",
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                meta={
                    "bfs_max_depth": int(edge_config.bfs_max_depth),
                    "origin_node_count": len(origins),
                    "candidate_limit": candidate_limit,
                    "count": len(expanded),
                },
                items=[_edge_brief(e) for e in expanded],
            )
        )
        search_results.append(expanded)

    edge_uuid_map: dict[str, Any] = {
        edge.uuid: edge for result in search_results for edge in result
    }

    # --- Rank ---
    reranker = edge_config.reranker
    started = time.perf_counter()
    reranked_uuids, edge_scores = await _rerank_edges(
        reranker=reranker,
        query=query,
        search_results=search_results,
        edge_uuid_map=edge_uuid_map,
        query_vector=query_vector,
        cross_encoder=cross_encoder,
        driver=driver,
        limit=limit,
        mmr_lambda=getattr(edge_config, "mmr_lambda", 0.5),
        reranker_min_score=reranker_min_score,
    )
    reranked_edges = [edge_uuid_map[uuid] for uuid in reranked_uuids if uuid in edge_uuid_map]
    score_by_uuid = dict(zip(reranked_uuids, edge_scores))
    trace.add_stage(
        StageRecord(
            kind="rank",
            label=f"Rank · {_reranker_name(reranker)}",
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
            meta={
                "reranker": _reranker_name(reranker),
                "candidate_count": len(edge_uuid_map),
                "reranked_count": len(reranked_edges),
                "returned_count": min(len(reranked_edges), limit),
            },
            items=[
                _edge_brief(edge, score=score_by_uuid.get(edge.uuid))
                for edge in reranked_edges[:limit]
            ],
        )
    )

    final_edges = reranked_edges[:limit]

    # --- Temporal lens (documented as a stage; in 'current' mode the supersession
    # constraint is pushed into the leg queries via search_filter, so nothing should be
    # superseded here — we record the returned set's supersession to make that visible). ---
    superseded = [e for e in final_edges if _is_superseded(e)]
    # The lens applies no further filtering/ranking — it is an ECHO of the rerank result.
    # Re-sort the TRACE rows by valid_at (the "became true" date) so the stage reads as a
    # timeline rather than a duplicate of the rerank table. The RETURNED facts (below) keep
    # the rerank order the answerer relies on — only the trace echo is reordered. ISO strings
    # sort chronologically; facts with no valid_at sort last.
    lens_items = sorted(
        (_edge_brief(e, score=score_by_uuid.get(e.uuid)) for e in final_edges),
        key=lambda b: (b["valid_at"] is None, b["valid_at"] or ""),
    )
    trace.add_stage(
        StageRecord(
            kind="temporal",
            label="Temporal lens",
            elapsed_ms=0.0,
            meta={
                "lens": trace.temporal,
                "mechanism": "push_down" if trace.temporal == "current" else "keep_history",
                "returned": len(final_edges),
                "superseded_in_result": len(superseded),
                "row_order": "valid_at",
            },
            items=lens_items,
        )
    )

    capture.trace = trace
    return final_edges, score_by_uuid


async def _rerank_edges(
    *,
    reranker: Any,
    query: str,
    search_results: list[list[Any]],
    edge_uuid_map: dict[str, Any],
    query_vector: list[float],
    cross_encoder: Any,
    driver: Any,
    limit: int,
    mmr_lambda: float,
    reranker_min_score: float,
) -> tuple[list[str], list[float]]:
    """Replicate graphiti edge_search reranking for rrf / mmr / cross_encoder.

    Any other reranker (node_distance / episode_mentions — not produced by our edge
    recipes) falls back to rrf so the trace stays meaningful rather than raising."""
    if reranker == EdgeReranker.cross_encoder:
        # graphiti ranks only the first ``limit`` unique candidates, in insertion order
        # (bm25 → cosine → bfs), against the original query text.
        fact_to_uuid_map = {
            edge.fact: edge.uuid for edge in list(edge_uuid_map.values())[:limit]
        }
        reranked_facts = await cross_encoder.rank(query, list(fact_to_uuid_map.keys()))
        uuids = [
            fact_to_uuid_map[fact]
            for fact, score in reranked_facts
            if score >= reranker_min_score
        ]
        scores = [score for _, score in reranked_facts if score >= reranker_min_score]
        return uuids, scores

    if reranker == EdgeReranker.mmr:
        uuids_and_vectors = await get_embeddings_for_edges(driver, list(edge_uuid_map.values()))
        return maximal_marginal_relevance(
            query_vector, uuids_and_vectors, mmr_lambda, reranker_min_score
        )

    # rrf (default) + any unhandled reranker.
    search_result_uuids = [[edge.uuid for edge in result] for result in search_results]
    return rrf(search_result_uuids, min_score=reranker_min_score)


async def search_nodes_traced(
    clients: Any,
    query: str,
    query_vector: list[float],
    *,
    group_ids: list[str] | None,
    node_config: Any,
    search_filter: Any,
    limit: int,
    reranker_min_score: float,
    trace: RetrievalTrace,
) -> tuple[list[Any], dict[str, float | None]]:
    """Re-host graphiti's ``node_search`` (entity lane) with per-stage capture.

    Same shape as the edge pipeline (bm25/cosine/bfs legs → rrf/mmr/cross_encoder), but
    over entity NODES: the cross-encoder ranks on ``node.name`` over ALL candidates (no
    ``[:limit]`` pre-trim, unlike edges), and there is no temporal lens (entities carry no
    fact supersession). Stages are tagged ``lane="node"``."""
    driver = clients.driver
    cross_encoder = clients.cross_encoder
    candidate_limit = 2 * limit
    methods = list(node_config.search_methods)

    search_results: list[list[Any]] = []
    if NodeSearchMethod.bm25 in methods:
        started = time.perf_counter()
        bm25 = await node_fulltext_search(driver, query, search_filter, group_ids, candidate_limit)
        trace.add_stage(
            StageRecord(
                kind="candidate",
                label="Keyword leg · BM25",
                lane="node",
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                meta={"method": "bm25", "candidate_limit": candidate_limit, "count": len(bm25)},
                items=[_node_brief(n) for n in bm25],
            )
        )
        search_results.append(bm25)
    if NodeSearchMethod.cosine_similarity in methods:
        started = time.perf_counter()
        cosine = await node_similarity_search(
            driver,
            query_vector,
            search_filter,
            group_ids,
            candidate_limit,
            getattr(node_config, "sim_min_score", 0.0),
        )
        trace.add_stage(
            StageRecord(
                kind="candidate",
                label="Meaning leg · cosine",
                lane="node",
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                meta={
                    "method": "cosine_similarity",
                    "candidate_limit": candidate_limit,
                    "sim_min_score": float(getattr(node_config, "sim_min_score", 0.0)),
                    "count": len(cosine),
                },
                items=[_node_brief(n) for n in cosine],
            )
        )
        search_results.append(cosine)
    if NodeSearchMethod.bfs in methods:
        origins = [node.uuid for result in search_results for node in result]
        started = time.perf_counter()
        expanded = await node_bfs_search(
            driver, origins, search_filter, node_config.bfs_max_depth, group_ids, candidate_limit
        )
        trace.add_stage(
            StageRecord(
                kind="hop",
                label="Hop expansion · BFS",
                lane="node",
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                meta={
                    "bfs_max_depth": int(node_config.bfs_max_depth),
                    "origin_node_count": len(origins),
                    "candidate_limit": candidate_limit,
                    "count": len(expanded),
                },
                items=[_node_brief(n) for n in expanded],
            )
        )
        search_results.append(expanded)

    node_uuid_map: dict[str, Any] = {n.uuid: n for result in search_results for n in result}

    reranker = node_config.reranker
    started = time.perf_counter()
    if reranker == NodeReranker.cross_encoder:
        name_to_uuid = {n.name: n.uuid for n in node_uuid_map.values()}
        reranked = await cross_encoder.rank(query, list(name_to_uuid.keys()))
        reranked_uuids = [name_to_uuid[n] for n, s in reranked if s >= reranker_min_score]
        scores = [s for _, s in reranked if s >= reranker_min_score]
    elif reranker == NodeReranker.mmr:
        uuids_and_vectors = await get_embeddings_for_nodes(driver, list(node_uuid_map.values()))
        reranked_uuids, scores = maximal_marginal_relevance(
            query_vector, uuids_and_vectors, getattr(node_config, "mmr_lambda", 0.5),
            reranker_min_score,
        )
    else:  # rrf + any unhandled
        reranked_uuids, scores = rrf(
            [[n.uuid for n in result] for result in search_results], min_score=reranker_min_score
        )
    reranked_nodes = [node_uuid_map[u] for u in reranked_uuids if u in node_uuid_map]
    score_by_uuid = dict(zip(reranked_uuids, scores))
    trace.add_stage(
        StageRecord(
            kind="rank",
            label=f"Rank · {_reranker_name(reranker)}",
            lane="node",
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
            meta={
                "reranker": _reranker_name(reranker),
                "candidate_count": len(node_uuid_map),
                "reranked_count": len(reranked_nodes),
                "returned_count": min(len(reranked_nodes), limit),
            },
            items=[_node_brief(n, score=score_by_uuid.get(n.uuid)) for n in reranked_nodes[:limit]],
        )
    )
    # Return the uuid→score map alongside the nodes so the recall path can show the same
    # per-entity score the trace does (graphiti never writes it back onto the node object).
    return reranked_nodes[:limit], score_by_uuid


async def search_episodes_traced(
    clients: Any,
    query: str,
    *,
    group_ids: list[str] | None,
    episode_config: Any,
    search_filter: Any,
    limit: int,
    reranker_min_score: float,
    trace: RetrievalTrace,
) -> tuple[list[Any], dict[str, float | None]]:
    """Re-host graphiti's ``episode_search`` (episode lane) with per-stage capture.

    Episodes are BM25-only (one candidate leg), then rrf — or, under cross_encoder, an rrf
    seed cut to ``limit`` then re-ranked on episode ``content``. Stages are tagged
    ``lane="episode"``; no hop, no temporal lens."""
    driver = clients.driver
    cross_encoder = clients.cross_encoder
    candidate_limit = 2 * limit

    started = time.perf_counter()
    bm25 = await episode_fulltext_search(driver, query, search_filter, group_ids, candidate_limit)
    trace.add_stage(
        StageRecord(
            kind="candidate",
            label="Keyword leg · BM25",
            lane="episode",
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
            meta={"method": "bm25", "candidate_limit": candidate_limit, "count": len(bm25)},
            items=[_episode_brief(e) for e in bm25],
        )
    )
    search_results = [bm25]
    episode_uuid_map: dict[str, Any] = {e.uuid: e for result in search_results for e in result}

    reranker = episode_config.reranker
    started = time.perf_counter()
    if reranker == EpisodeReranker.cross_encoder:
        rrf_uuids, _ = rrf(
            [[e.uuid for e in result] for result in search_results], min_score=reranker_min_score
        )
        rrf_results = [episode_uuid_map[u] for u in rrf_uuids][:limit]
        content_to_uuid = {e.content: e.uuid for e in rrf_results}
        reranked = await cross_encoder.rank(query, list(content_to_uuid.keys()))
        reranked_uuids = [content_to_uuid[c] for c, s in reranked if s >= reranker_min_score]
        scores = [s for _, s in reranked if s >= reranker_min_score]
    else:  # rrf + any unhandled
        reranked_uuids, scores = rrf(
            [[e.uuid for e in result] for result in search_results], min_score=reranker_min_score
        )
    reranked_eps = [episode_uuid_map[u] for u in reranked_uuids if u in episode_uuid_map]
    score_by_uuid = dict(zip(reranked_uuids, scores))
    trace.add_stage(
        StageRecord(
            kind="rank",
            label=f"Rank · {_reranker_name(reranker)}",
            lane="episode",
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
            meta={
                "reranker": _reranker_name(reranker),
                "candidate_count": len(episode_uuid_map),
                "reranked_count": len(reranked_eps),
                "returned_count": min(len(reranked_eps), limit),
            },
            items=[_episode_brief(e, score=score_by_uuid.get(e.uuid)) for e in reranked_eps[:limit]],
        )
    )
    # Return the uuid→score map alongside the episodes (same reason as the node lane above).
    return reranked_eps[:limit], score_by_uuid


def _reranker_name(reranker: Any) -> str:
    return getattr(reranker, "value", None) or str(reranker)


__all__ = ["search_episodes_traced", "search_facts_traced", "search_nodes_traced"]
