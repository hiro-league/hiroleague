"""Parity + stage-capture tests for the re-hosted Graphiti fact-search pipeline.

The re-host (``search_facts_traced``) replicates graphiti's ``edge_search``. A true
end-to-end parity check needs a live Kuzu graph + embedder + extraction LLM (an
integration concern), so here we pin the **orchestration** instead: monkeypatch the
shared ``search_utils`` leg functions in BOTH modules and assert the re-host returns
the SAME fused/limited edges as graphiti's real ``edge_search``, while also capturing
the per-stage trace. If graphiti's orchestration changes, the compat guard trips; if
our re-host diverges, this parity assertion trips.
"""

from __future__ import annotations

import copy
import datetime as dt
from types import SimpleNamespace

import pytest
from graphiti_core.search import search as gsearch
from graphiti_core.search.search import edge_search, episode_search, node_search
from graphiti_core.search.search_config import (
    EpisodeReranker,
    EpisodeSearchConfig,
    EpisodeSearchMethod,
    NodeReranker,
    NodeSearchConfig,
    NodeSearchMethod,
)
from graphiti_core.search.search_config_recipes import EDGE_HYBRID_SEARCH_RRF
from graphiti_core.search.search_filters import SearchFilters

from hirocli.services.knowledge.graph import graphiti_fact_search
from hirocli.services.knowledge.graph.graphiti_fact_search import (
    search_episodes_traced,
    search_facts_traced,
    search_nodes_traced,
)
from hirocli.services.knowledge.graph.retrieval_trace import RetrievalCapture, RetrievalTrace


class _Edge:
    def __init__(self, uuid: str, fact: str) -> None:
        self.uuid = uuid
        self.fact = fact
        self.name = "REL"
        self.source_node_uuid = f"s-{uuid}"
        self.target_node_uuid = f"t-{uuid}"
        self.episodes = [f"chunk-{uuid}"]
        self.valid_at = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
        self.invalid_at = None
        self.expired_at = None


def _patch_legs(monkeypatch, bm25: list[_Edge], cosine: list[_Edge]) -> None:
    async def fake_bm25(*_a, **_k):
        return list(bm25)

    async def fake_cosine(*_a, **_k):
        return list(cosine)

    # Patch in graphiti's search module (its edge_search binding) AND our re-host module.
    monkeypatch.setattr(gsearch, "edge_fulltext_search", fake_bm25)
    monkeypatch.setattr(gsearch, "edge_similarity_search", fake_cosine)
    monkeypatch.setattr(graphiti_fact_search, "edge_fulltext_search", fake_bm25)
    monkeypatch.setattr(graphiti_fact_search, "edge_similarity_search", fake_cosine)


def _new_trace() -> RetrievalTrace:
    return RetrievalTrace(
        query="q",
        group_id="kb_main",
        recipe="rrf",
        temporal="current",
        num_results=2,
        sim_min_score=0.3,
        k_hop=1,
    )


@pytest.mark.asyncio
async def test_rehost_matches_graphiti_edge_search_rrf(monkeypatch) -> None:
    bm25 = [_Edge("a", "fa"), _Edge("b", "fb"), _Edge("c", "fc")]
    cosine = [_Edge("c", "fc"), _Edge("d", "fd"), _Edge("e", "fe")]
    _patch_legs(monkeypatch, bm25, cosine)

    cfg = copy.deepcopy(EDGE_HYBRID_SEARCH_RRF.edge_config)

    g_edges, _g_scores = await edge_search(
        object(),
        None,
        "q",
        [0.1, 0.2],
        ["kb_main"],
        cfg,
        SearchFilters(),
        limit=2,
        reranker_min_score=0,
    )

    capture = RetrievalCapture()
    my_edges, edge_scores = await search_facts_traced(
        SimpleNamespace(driver=object(), cross_encoder=None, embedder=None),
        "q",
        [0.1, 0.2],
        group_ids=["kb_main"],
        edge_config=cfg,
        search_filter=SearchFilters(),
        limit=2,
        reranker_min_score=0,
        capture=capture,
        trace=_new_trace(),
    )

    assert [e.uuid for e in my_edges] == [e.uuid for e in g_edges]
    assert len(my_edges) == 2  # limit applied
    # The score map is keyed by the returned edges' uuids (surfaced onto recall fact rows).
    assert set(edge_scores) >= {e.uuid for e in my_edges}


@pytest.mark.asyncio
async def test_rehost_records_each_stage(monkeypatch) -> None:
    bm25 = [_Edge("a", "fa"), _Edge("b", "fb")]
    cosine = [_Edge("b", "fb"), _Edge("c", "fc")]
    _patch_legs(monkeypatch, bm25, cosine)
    cfg = copy.deepcopy(EDGE_HYBRID_SEARCH_RRF.edge_config)

    capture = RetrievalCapture()
    await search_facts_traced(
        SimpleNamespace(driver=object(), cross_encoder=None, embedder=None),
        "q",
        [0.1],
        group_ids=["kb_main"],
        edge_config=cfg,
        search_filter=SearchFilters(),
        limit=2,
        reranker_min_score=0,
        capture=capture,
        trace=_new_trace(),
    )

    assert capture.trace is not None
    kinds = [s.kind for s in capture.trace.stages]
    # rrf recipe = two candidate legs (bm25, cosine), then rank, then temporal (no bfs/hop).
    assert kinds == ["candidate", "candidate", "rank", "temporal"]

    candidate_bm25 = capture.trace.stages[0]
    assert candidate_bm25.meta["method"] == "bm25"
    assert [i["uuid"] for i in candidate_bm25.items] == ["a", "b"]

    rank_stage = capture.trace.stages[2]
    # EdgeReranker.rrf.value is the canonical graphiti name.
    assert rank_stage.meta["reranker"] == "reciprocal_rank_fusion"
    # Rank items carry fused scores (candidate legs leave score=None; rank fills it).
    assert all(i["score"] is not None for i in rank_stage.items)


# ── Node (entity) lane ─────────────────────────────────────────────────────────────────────
class _Node:
    def __init__(self, uuid: str, name: str) -> None:
        self.uuid = uuid
        self.name = name
        self.summary = f"summary of {name}"
        self.labels = ["Entity", "Person"]
        self.group_id = "kb_main"


def _patch_node_legs(monkeypatch, bm25: list[_Node], cosine: list[_Node]) -> None:
    async def fake_bm25(*_a, **_k):
        return list(bm25)

    async def fake_cosine(*_a, **_k):
        return list(cosine)

    monkeypatch.setattr(gsearch, "node_fulltext_search", fake_bm25)
    monkeypatch.setattr(gsearch, "node_similarity_search", fake_cosine)
    monkeypatch.setattr(graphiti_fact_search, "node_fulltext_search", fake_bm25)
    monkeypatch.setattr(graphiti_fact_search, "node_similarity_search", fake_cosine)


@pytest.mark.asyncio
async def test_node_rehost_matches_graphiti_node_search_rrf(monkeypatch) -> None:
    bm25 = [_Node("a", "Adam"), _Node("b", "Bea"), _Node("c", "Cy")]
    cosine = [_Node("c", "Cy"), _Node("d", "Dee"), _Node("e", "Eve")]
    _patch_node_legs(monkeypatch, bm25, cosine)

    cfg = NodeSearchConfig(
        search_methods=[NodeSearchMethod.bm25, NodeSearchMethod.cosine_similarity],
        reranker=NodeReranker.rrf,
        sim_min_score=0.3,
        bfs_max_depth=1,
    )

    g_nodes, _g_scores = await node_search(
        object(), None, "q", [0.1, 0.2], ["kb_main"], cfg, SearchFilters(),
        limit=2, reranker_min_score=0,
    )

    nodes, _scores = await search_nodes_traced(
        SimpleNamespace(driver=object(), cross_encoder=None, embedder=None),
        "q",
        [0.1, 0.2],
        group_ids=["kb_main"],
        node_config=cfg,
        search_filter=SearchFilters(),
        limit=2,
        reranker_min_score=0,
        trace=_new_trace(),
    )

    assert [n.uuid for n in nodes] == [n.uuid for n in g_nodes]
    assert len(nodes) == 2


@pytest.mark.asyncio
async def test_node_rehost_records_lane_and_columns(monkeypatch) -> None:
    bm25 = [_Node("a", "Adam"), _Node("b", "Bea")]
    cosine = [_Node("b", "Bea"), _Node("c", "Cy")]
    _patch_node_legs(monkeypatch, bm25, cosine)
    cfg = NodeSearchConfig(
        search_methods=[NodeSearchMethod.bm25, NodeSearchMethod.cosine_similarity],
        reranker=NodeReranker.rrf,
        sim_min_score=0.3,
        bfs_max_depth=1,
    )

    trace = _new_trace()
    await search_nodes_traced(
        SimpleNamespace(driver=object(), cross_encoder=None, embedder=None),
        "q",
        [0.1],
        group_ids=["kb_main"],
        node_config=cfg,
        search_filter=SearchFilters(),
        limit=2,
        reranker_min_score=0,
        trace=trace,
    )

    assert [s.kind for s in trace.stages] == ["candidate", "candidate", "rank"]
    assert all(s.lane == "node" for s in trace.stages)
    first = trace.stages[0].items[0]
    assert first["name"] == "Adam"
    assert first["entity_type"] == "Person"  # first non-base label
    assert "summary" in first


# ── Episode lane ───────────────────────────────────────────────────────────────────────────
class _Episode:
    def __init__(self, uuid: str, content: str) -> None:
        self.uuid = uuid
        self.content = content
        self.source = "message"
        self.source_description = "chat"
        self.valid_at = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)


def _patch_episode_leg(monkeypatch, bm25: list[_Episode]) -> None:
    async def fake_bm25(*_a, **_k):
        return list(bm25)

    monkeypatch.setattr(gsearch, "episode_fulltext_search", fake_bm25)
    monkeypatch.setattr(graphiti_fact_search, "episode_fulltext_search", fake_bm25)


@pytest.mark.asyncio
async def test_episode_rehost_matches_graphiti_episode_search_rrf(monkeypatch) -> None:
    bm25 = [_Episode("a", "turn a"), _Episode("b", "turn b"), _Episode("c", "turn c")]
    _patch_episode_leg(monkeypatch, bm25)

    cfg = EpisodeSearchConfig(
        search_methods=[EpisodeSearchMethod.bm25], reranker=EpisodeReranker.rrf
    )

    g_eps, _g_scores = await episode_search(
        object(), None, "q", [0.1, 0.2], ["kb_main"], cfg, SearchFilters(),
        limit=2, reranker_min_score=0,
    )

    eps, _scores = await search_episodes_traced(
        SimpleNamespace(driver=object(), cross_encoder=None, embedder=None),
        "q",
        group_ids=["kb_main"],
        episode_config=cfg,
        search_filter=SearchFilters(),
        limit=2,
        reranker_min_score=0,
        trace=_new_trace(),
    )

    assert [e.uuid for e in eps] == [e.uuid for e in g_eps]
    assert len(eps) == 2


@pytest.mark.asyncio
async def test_episode_rehost_records_lane_and_columns(monkeypatch) -> None:
    bm25 = [_Episode("a", "turn a"), _Episode("b", "turn b")]
    _patch_episode_leg(monkeypatch, bm25)
    cfg = EpisodeSearchConfig(
        search_methods=[EpisodeSearchMethod.bm25], reranker=EpisodeReranker.rrf
    )

    trace = _new_trace()
    await search_episodes_traced(
        SimpleNamespace(driver=object(), cross_encoder=None, embedder=None),
        "q",
        group_ids=["kb_main"],
        episode_config=cfg,
        search_filter=SearchFilters(),
        limit=2,
        reranker_min_score=0,
        trace=trace,
    )

    assert [s.kind for s in trace.stages] == ["candidate", "rank"]
    assert all(s.lane == "episode" for s in trace.stages)
    first = trace.stages[0].items[0]
    assert first["content"] == "turn a"
    assert first["valid_at"] is not None
