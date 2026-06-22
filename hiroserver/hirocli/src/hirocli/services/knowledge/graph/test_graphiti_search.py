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
    exp = await search_chunk_ids(g, "where does adam live now", group_id="kb_main", temporal="current")
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
    exp = await search_chunk_ids(g, "history", group_id="kb_main", temporal="all")
    assert set(exp.chunk_ids) == {"c1", "c2"}
    assert exp.facts_used == 2


@pytest.mark.asyncio
async def test_current_pushes_down_searchfilters() -> None:
    """temporal=current must push a current-only SearchFilters into the query (§7) —
    not rely on the Python post-drop. invalid_at + expired_at are filtered IS NULL."""
    from graphiti_core.search.search_filters import ComparisonOperator

    g = _FakeGraphiti([_Edge(["c1"], "Adam lives in Cambridge")])
    await search_chunk_ids(g, "where does adam live now", group_id="kb_main", temporal="current")
    sf = g.calls[0]["search_filter"]
    assert sf is not None, "current must push down a SearchFilters"
    # Both temporal bounds filtered as IS NULL ⇒ only non-superseded facts returned.
    assert sf.invalid_at[0][0].comparison_operator is ComparisonOperator.is_null
    assert sf.expired_at[0][0].comparison_operator is ComparisonOperator.is_null


@pytest.mark.asyncio
async def test_all_passes_no_searchfilters() -> None:
    """temporal=all must NOT constrain time — search_filter stays None (history kept)."""
    g = _FakeGraphiti([_Edge(["c1"], "f")])
    await search_chunk_ids(g, "history", group_id="kb_main", temporal="all")
    assert g.calls[0]["search_filter"] is None


@pytest.mark.asyncio
async def test_expired_at_is_superseded() -> None:
    g = _FakeGraphiti([_Edge(["c1"], "expired fact", expired_at=_past())])
    exp = await search_chunk_ids(g, "q", group_id="kb_main", temporal="current")
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
async def test_missing_group_id_is_safe_noop() -> None:
    """Firm group-ID policy (docs/graph-group-policy-design.md §6): a scoped read MUST name a
    partition. A missing group_id no longer becomes ``group_ids=None`` (an all-groups scan that
    leaked conversation memory into knowledge) — it fails SAFE to an empty expansion, and the
    search is never even issued."""
    g = _FakeGraphiti([_Edge(["c1"], "f")])
    exp = await search_chunk_ids(g, "q")
    assert exp.chunk_ids == ()
    assert g.calls == []  # never scanned all groups


@pytest.mark.asyncio
async def test_search_error_propagates() -> None:
    class _Boom:
        async def search_(self, *a, **k):
            raise RuntimeError("kuzu down")

    with pytest.raises(RuntimeError, match="kuzu down"):
        await search_chunk_ids(_Boom(), "q", group_id="kb_main")


@pytest.mark.asyncio
async def test_recipe_k_hop_min_relevance_thread_into_config() -> None:
    """The admin knobs (recipe / k_hop / min_relevance) must reach the SearchConfig —
    else they are dead prefs (the gap this fix closes)."""
    from graphiti_core.search.search_config import EdgeReranker

    g = _FakeGraphiti([_Edge(["c1"], "f")])
    await search_chunk_ids(
        g,
        "q",
        group_id="kb_main",
        num_results=7,
        recipe="cross_encoder",
        k_hop=3,
        min_relevance=0.4,
        sim_min_score=0.2,
    )
    config = g.calls[0]["config"]
    assert config.limit == 7  # num_results → SearchConfig.limit
    assert config.reranker_min_score == pytest.approx(0.4)  # min_relevance gate
    assert config.edge_config.bfs_max_depth == 3  # k_hop → bfs depth
    assert config.edge_config.reranker is EdgeReranker.cross_encoder  # recipe selected
    # sim_min_score → cosine candidate floor (overrides graphiti's strict 0.6 default,
    # the gap that made trivial fact searches return facts_0/0).
    assert config.edge_config.sim_min_score == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_sim_min_score_defaults_below_graphiti_strict_floor() -> None:
    """The cosine candidate floor must default below graphiti's hardcoded 0.6 — that
    strict default is exactly what made paraphrase-distant fact searches return 0/0."""
    g = _FakeGraphiti([_Edge(["c1"], "f")])
    await search_chunk_ids(g, "q", group_id="kb_main")  # no sim_min_score → recall-oriented default
    assert g.calls[0]["config"].edge_config.sim_min_score < 0.6


@pytest.mark.asyncio
async def test_unknown_recipe_falls_back_to_rrf() -> None:
    from graphiti_core.search.search_config import EdgeReranker

    g = _FakeGraphiti([_Edge(["c1"], "f")])
    await search_chunk_ids(g, "q", group_id="kb_main", recipe="bogus")
    assert g.calls[0]["config"].edge_config.reranker is EdgeReranker.rrf


@pytest.mark.asyncio
async def test_service_search_chunk_ids_group_override() -> None:
    """memory Phase 1: GraphitiMemoryService.search_chunk_ids(group_id=...) overrides the
    service's default (knowledge) group, so memory recall searches its own
    per-(user,character) partition and threads the admin search knobs through."""
    from hirocli.services.knowledge.graph.graphiti_service import GraphitiMemoryService

    svc = object.__new__(GraphitiMemoryService)
    fake = _FakeGraphiti([_Edge(["c1"], "User lives in Tokyo")])
    svc._graphiti = fake  # type: ignore[attr-defined]
    svc._group_id = "kb_main"  # type: ignore[attr-defined]  # service default (named knowledge group)
    svc._search_recipe = "rrf"  # type: ignore[attr-defined]
    svc._search_scope = "edges"  # type: ignore[attr-defined]
    svc._k_hop = 1  # type: ignore[attr-defined]
    svc._reranker_min_score = 0.0  # type: ignore[attr-defined]
    svc._sim_min_score = 0.3  # type: ignore[attr-defined]

    exp = await svc.search_chunk_ids("where does the user live", group_id="mem_42_aria")

    assert fake.calls[0]["group_ids"] == ["mem_42_aria"]  # override, not the default
    assert exp.facts_used == 1


@pytest.mark.asyncio
async def test_recipe_constant_not_mutated() -> None:
    """_build_search_config must deep-copy the shared recipe constant (no leakage)."""
    from graphiti_core.search.search_config_recipes import EDGE_HYBRID_SEARCH_RRF

    before = EDGE_HYBRID_SEARCH_RRF.limit
    g = _FakeGraphiti([_Edge(["c1"], "f")])
    await search_chunk_ids(g, "q", group_id="kb_main", num_results=99)
    assert EDGE_HYBRID_SEARCH_RRF.limit == before  # untouched


@pytest.mark.asyncio
async def test_search_chunk_ids_show_expiry_false_keeps_valid_at_hides_until() -> None:
    # Fidelity fix (item 4): valid_at ("as of") is ALWAYS surfaced, even with show_expiry off;
    # only invalid_at ("until") stays gated. superseded is dropped entirely (item 5).
    g = _FakeGraphiti([_Edge(["c1"], "Adam lives in Boston", invalid_at=_past())])
    exp = await search_chunk_ids(
        g, "history", group_id="kb_main", temporal="all", show_expiry=False
    )
    assert exp.fact_rows
    row = exp.fact_rows[0]
    assert "valid_at" in row
    assert "invalid_at" not in row
    assert "superseded" not in row


@pytest.mark.asyncio
async def test_search_chunk_ids_show_expiry_true_emits_until_on_edges() -> None:
    past = _past()
    g = _FakeGraphiti([_Edge(["c1"], "Adam lived in Boston", invalid_at=past)])
    exp = await search_chunk_ids(
        g, "history", group_id="kb_main", temporal="all", show_expiry=True
    )
    assert exp.fact_rows
    row = exp.fact_rows[0]
    assert row["valid_at"] == ""
    assert row["invalid_at"] == past.date().isoformat()
    # superseded dropped (item 5): retirement is conveyed by `until` (invalid_at).
    assert "superseded" not in row


@pytest.mark.asyncio
async def test_search_chunk_ids_show_expiry_only_on_edges() -> None:
    class _Node:
        def __init__(self) -> None:
            self.summary = "A reader"
            self.name = "Ada"
            self.uuid = "n1"
            self.labels = ["Person"]

    class _Episode:
        def __init__(self) -> None:
            self.content = "I love sci-fi."
            self.uuid = "e1"
            self.valid_at = _past()

    class _WideResults:
        def __init__(self) -> None:
            self.edges = [_Edge(["c1"], "Ada loves sci-fi")]
            self.nodes = [_Node()]
            self.episodes = [_Episode()]

    class _WideGraphiti(_FakeGraphiti):
        async def search_(self, query, config=None, group_ids=None, search_filter=None):
            self.calls.append(
                {
                    "query": query,
                    "config": config,
                    "group_ids": group_ids,
                    "num_results": getattr(config, "limit", None),
                    "search_filter": search_filter,
                }
            )
            return _WideResults()

    g = _WideGraphiti([])
    exp = await search_chunk_ids(
        g,
        "sci-fi",
        group_id="kb_main",
        scope="edges_nodes_episodes",
        show_expiry=True,
    )
    # superseded is dropped from fact rows (item 5); invalid_at ("until") shows on edges under
    # show_expiry but never on nodes/episodes.
    assert "superseded" not in exp.fact_rows[0]
    assert "invalid_at" in exp.fact_rows[0]
    assert "superseded" not in exp.node_rows[0]
    assert "invalid_at" not in exp.node_rows[0]
    assert "superseded" not in exp.episode_rows[0]
    assert "invalid_at" not in exp.episode_rows[0]
