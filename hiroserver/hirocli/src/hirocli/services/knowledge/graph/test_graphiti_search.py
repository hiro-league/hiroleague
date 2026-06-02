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


class _FakeGraphiti:
    def __init__(self, edges: list) -> None:
        self._edges = edges
        self.calls: list[dict] = []

    async def search(self, query, group_ids=None, num_results=20):
        self.calls.append({"query": query, "group_ids": group_ids, "num_results": num_results})
        return self._edges


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
        async def search(self, *a, **k):
            raise RuntimeError("kuzu down")

    with pytest.raises(RuntimeError, match="kuzu down"):
        await search_chunk_ids(_Boom(), "q")
