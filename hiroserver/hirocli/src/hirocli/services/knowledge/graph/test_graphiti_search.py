"""Tests for Graphiti retrieval (query → fact edges → chunk_ids).

Pure: a fake Graphiti client returns canned fact edges — no Kuzu, no model.
Verifies chunk_id union, the temporal filter (current drops superseded; all keeps),
fact collection, empty-query no-op, group_id passthrough, and error propagation.
"""

from __future__ import annotations

import datetime as dt

import pytest

from hirocli.services.knowledge.graph.graphiti_search import search_chunk_ids


class _Edge:
    def __init__(self, episodes, fact, *, invalid_at=None, expired_at=None) -> None:
        self.episodes = episodes
        self.fact = fact
        self.invalid_at = invalid_at
        self.expired_at = expired_at


class _Results:
    """Minimal stand-in for graphiti ``SearchResults`` (only ``.edges`` is read)."""

    def __init__(self, edges: list) -> None:
        self.edges = edges


class _FakeGraphiti:
    def __init__(self, edges: list) -> None:
        self._edges = edges
        self.calls: list[dict] = []

    async def search_(self, query, config=None, group_ids=None, search_filter=None):
        self.calls.append(
            {
                "query": query,
                "config": config,
                "group_ids": group_ids,
                # config.limit is the staged-search analog of the old num_results.
                "num_results": getattr(config, "limit", None),
                "search_filter": search_filter,
            }
        )
        return _Results(self._edges)


def _past() -> dt.datetime:
    return dt.datetime(2024, 1, 1, tzinfo=dt.UTC)


@pytest.mark.asyncio
async def test_union_chunk_ids_and_facts() -> None:
    g = _FakeGraphiti(
        [
            _Edge(["c1", "c2"], "Adam works at Cedar Labs"),
            _Edge(["c2", "c3"], "Adam lives in Cambridge"),
        ]
    )
    exp = await search_chunk_ids(g, "where does adam work", group_id="grp", num_results=10)
    assert exp.chunk_ids == ("c1", "c2", "c3")  # sorted, deduped
    assert exp.facts_total == 2
    assert exp.facts_used == 2
    assert "Adam works at Cedar Labs" in exp.facts
    assert g.calls[0]["group_ids"] == ["grp"]
    assert g.calls[0]["num_results"] == 10


@pytest.mark.asyncio
async def test_temporal_current_drops_superseded() -> None:
    g = _FakeGraphiti(
        [
            _Edge(["c1"], "Adam lives in Cambridge"),
            _Edge(["c2"], "Adam lives in Boston", invalid_at=_past()),
        ]
    )
    exp = await search_chunk_ids(g, "where does adam live now", temporal="current")
    assert exp.chunk_ids == ("c1",)
    assert exp.facts_used == 1
    assert exp.facts_total == 2


@pytest.mark.asyncio
async def test_temporal_all_keeps_superseded() -> None:
    g = _FakeGraphiti(
        [
            _Edge(["c1"], "current", invalid_at=None),
            _Edge(["c2"], "old", invalid_at=_past()),
        ]
    )
    exp = await search_chunk_ids(g, "history", temporal="all")
    assert set(exp.chunk_ids) == {"c1", "c2"}
    assert exp.facts_used == 2


@pytest.mark.asyncio
async def test_current_pushes_down_searchfilters() -> None:
    """temporal=current must push a current-only SearchFilters into the query (§7) —
    not rely on the Python post-drop. invalid_at + expired_at are filtered IS NULL."""
    from graphiti_core.search.search_filters import ComparisonOperator

    g = _FakeGraphiti([_Edge(["c1"], "Adam lives in Cambridge")])
    await search_chunk_ids(g, "where does adam live now", temporal="current")
    sf = g.calls[0]["search_filter"]
    assert sf is not None, "current must push down a SearchFilters"
    # Both temporal bounds filtered as IS NULL ⇒ only non-superseded facts returned.
    assert sf.invalid_at[0][0].comparison_operator is ComparisonOperator.is_null
    assert sf.expired_at[0][0].comparison_operator is ComparisonOperator.is_null


@pytest.mark.asyncio
async def test_all_passes_no_searchfilters() -> None:
    """temporal=all must NOT constrain time — search_filter stays None (history kept)."""
    g = _FakeGraphiti([_Edge(["c1"], "f")])
    await search_chunk_ids(g, "history", temporal="all")
    assert g.calls[0]["search_filter"] is None


@pytest.mark.asyncio
async def test_expired_at_is_superseded() -> None:
    g = _FakeGraphiti([_Edge(["c1"], "expired fact", expired_at=_past())])
    exp = await search_chunk_ids(g, "q", temporal="current")
    assert exp.chunk_ids == ()
    assert exp.facts_used == 0
    assert exp.facts_total == 1


@pytest.mark.asyncio
async def test_blank_query_is_noop() -> None:
    g = _FakeGraphiti([_Edge(["c1"], "f")])
    exp = await search_chunk_ids(g, "   ")
    assert exp.chunk_ids == ()
    assert g.calls == []  # search not called


@pytest.mark.asyncio
async def test_no_group_id_passes_none() -> None:
    g = _FakeGraphiti([_Edge(["c1"], "f")])
    await search_chunk_ids(g, "q")
    assert g.calls[0]["group_ids"] is None


@pytest.mark.asyncio
async def test_search_error_propagates() -> None:
    class _Boom:
        async def search_(self, *a, **k):
            raise RuntimeError("kuzu down")

    with pytest.raises(RuntimeError, match="kuzu down"):
        await search_chunk_ids(_Boom(), "q")


@pytest.mark.asyncio
async def test_recipe_k_hop_min_relevance_thread_into_config() -> None:
    """The admin knobs (recipe / k_hop / min_relevance) must reach the SearchConfig —
    else they are dead prefs (the gap this fix closes)."""
    from graphiti_core.search.search_config import EdgeReranker

    g = _FakeGraphiti([_Edge(["c1"], "f")])
    await search_chunk_ids(
        g, "q", num_results=7, recipe="cross_encoder", k_hop=3, min_relevance=0.4
    )
    config = g.calls[0]["config"]
    assert config.limit == 7  # num_results → SearchConfig.limit
    assert config.reranker_min_score == pytest.approx(0.4)  # min_relevance gate
    assert config.edge_config.bfs_max_depth == 3  # k_hop → bfs depth
    assert config.edge_config.reranker is EdgeReranker.cross_encoder  # recipe selected


@pytest.mark.asyncio
async def test_unknown_recipe_falls_back_to_rrf() -> None:
    from graphiti_core.search.search_config import EdgeReranker

    g = _FakeGraphiti([_Edge(["c1"], "f")])
    await search_chunk_ids(g, "q", recipe="bogus")
    assert g.calls[0]["config"].edge_config.reranker is EdgeReranker.rrf


@pytest.mark.asyncio
async def test_recipe_constant_not_mutated() -> None:
    """_build_search_config must deep-copy the shared recipe constant (no leakage)."""
    from graphiti_core.search.search_config_recipes import EDGE_HYBRID_SEARCH_RRF

    before = EDGE_HYBRID_SEARCH_RRF.limit
    g = _FakeGraphiti([_Edge(["c1"], "f")])
    await search_chunk_ids(g, "q", num_results=99)
    assert EDGE_HYBRID_SEARCH_RRF.limit == before  # untouched
