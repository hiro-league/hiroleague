"""Tests for the search_memory retrieval-agent tool (P9: multi-arg, queries list)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from hirocli.domain.preferences import RetrievalAgentLimits
from hirocli.services.memory.agent.accumulator import Accumulator
from hirocli.services.memory.agent.search_tool import (
    SearchMemoryArgs,
    SearchMemoryQuery,
    SearchMemoryTool,
)
from hirocli.services.memory.graphiti_conversation import GraphitiConversationMemory


class _FakeGraph:
    observability = "ledger"

    def __init__(self, hits: list[dict] | None = None) -> None:
        self.search_calls: list[dict] = []
        self._hits = list(hits or [])

    async def search_chunk_ids(
        self,
        query,
        *,
        group_id,
        num_results,
        temporal,
        k_hop=None,
        show_expiry=False,
    ):
        self.search_calls.append(
            {
                "query": query,
                "group_id": group_id,
                "num_results": num_results,
                "temporal": temporal,
                "k_hop": k_hop,
                "show_expiry": show_expiry,
            }
        )
        fact_rows = tuple(dict(h) for h in self._hits if h.get("kind") in ("fact", "edge"))
        return SimpleNamespace(
            facts=tuple(h.get("memory", "") for h in self._hits),
            chunk_ids=(),
            facts_total=len(self._hits),
            facts_used=len(self._hits),
            fact_rows=fact_rows,
            node_rows=(),
            episode_rows=(),
            node_memories=(),
            episode_memories=(),
        )


def _tool(*, hits: list[dict] | None = None, limits: RetrievalAgentLimits | None = None) -> SearchMemoryTool:
    graph = _FakeGraph(hits)
    memory = GraphitiConversationMemory(graph, default_top_k=8, temporal_default="current")
    return SearchMemoryTool(
        memory=memory,
        accumulator=Accumulator(),
        limits=limits or RetrievalAgentLimits(),
        user_id=1,
        character_id="aria",
    )


def _args(*queries: SearchMemoryQuery) -> SearchMemoryArgs:
    return SearchMemoryArgs(queries=list(queries))


@pytest.mark.asyncio
async def test_clamps_limit_within_bounds() -> None:
    tool = _tool()
    await tool.call(_args(SearchMemoryQuery(query="budget", limit=999, temporal="current", hops=1)))
    assert tool._memory._graph.search_calls[0]["num_results"] == 40


@pytest.mark.asyncio
async def test_pydantic_rejects_hops_out_of_bounds() -> None:
    with pytest.raises(ValidationError):
        SearchMemoryQuery(query="budget", hops=4)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_empty_query_returns_zero_results() -> None:
    tool = _tool(hits=[{"kind": "fact", "uuid": "e1", "memory": "x", "fact": "x"}])
    result = await tool.call(_args(SearchMemoryQuery(query="   ", goal="empty")))
    sub = result.sub_results[0]
    assert sub.returned == 0
    assert sub.new == 0
    assert sub.items == []
    assert tool._memory._graph.search_calls == []


@pytest.mark.asyncio
async def test_dedup_against_accumulator() -> None:
    hits = [
        {"kind": "fact", "uuid": "e1", "memory": "Budget is $50", "fact": "Budget is $50"},
        {"kind": "fact", "uuid": "e2", "memory": "Likes sci-fi", "fact": "Likes sci-fi"},
    ]
    tool = _tool(hits=hits)
    first = await tool.call(_args(SearchMemoryQuery(query="budget and genre")))
    second = await tool.call(_args(SearchMemoryQuery(query="budget again", goal="retry")))
    assert first.sub_results[0].returned == 2
    assert first.sub_results[0].new == 2
    assert second.sub_results[0].returned == 2
    assert second.sub_results[0].new == 0
    assert second.accumulated_total == 2


@pytest.mark.asyncio
async def test_search_id_increments_per_sub_query() -> None:
    """sids are globally monotonic across sub-queries and across calls (UI highlight key)."""
    tool = _tool(hits=[])
    r1 = await tool.call(
        _args(SearchMemoryQuery(query="a"), SearchMemoryQuery(query="b"))
    )
    r2 = await tool.call(_args(SearchMemoryQuery(query="c")))
    assert [s.sid for s in r1.sub_results] == [1, 2]
    assert [s.sid for s in r2.sub_results] == [3]


@pytest.mark.asyncio
async def test_runs_sub_queries_and_groups_results() -> None:
    hits = [{"kind": "fact", "uuid": "e1", "memory": "fact", "fact": "fact"}]
    tool = _tool(hits=hits)
    result = await tool.call(
        _args(
            SearchMemoryQuery(query="job", goal="g1"),
            SearchMemoryQuery(query="hobby", goal="g2"),
            SearchMemoryQuery(query="trip", goal="g3", temporal="all"),
        )
    )
    assert [s.goal for s in result.sub_results] == ["g1", "g2", "g3"]
    assert len(tool._memory._graph.search_calls) == 3


@pytest.mark.asyncio
async def test_runtime_rejects_over_max_parallel() -> None:
    tool = _tool(limits=RetrievalAgentLimits(max_parallel_searches=2))
    with pytest.raises(ValueError, match="too many sub-queries"):
        await tool.call(
            _args(
                SearchMemoryQuery(query="a"),
                SearchMemoryQuery(query="b"),
                SearchMemoryQuery(query="c"),
            )
        )


@pytest.mark.asyncio
async def test_pydantic_rejects_above_hard_ceiling() -> None:
    with pytest.raises(ValidationError):
        SearchMemoryArgs(queries=[SearchMemoryQuery(query=f"q{i}") for i in range(6)])


@pytest.mark.asyncio
async def test_pydantic_rejects_empty_queries() -> None:
    with pytest.raises(ValidationError):
        SearchMemoryArgs(queries=[])


@pytest.mark.asyncio
async def test_propagates_show_expiry_to_search_chunk_ids() -> None:
    tool = _tool(hits=[])
    await tool.call(
        _args(
            SearchMemoryQuery(query="budget history", temporal="all", show_expiry=True, hops=2)
        )
    )
    call = tool._memory._graph.search_calls[0]
    assert call["show_expiry"] is True
    assert call["k_hop"] == 2
    assert call["temporal"] == "all"


@pytest.mark.asyncio
async def test_error_in_one_sub_query_captured_not_raised() -> None:
    """A failing sub-query becomes an error sub-result; siblings still run (no abort)."""

    class _BoomOnBad(_FakeGraph):
        async def search_chunk_ids(self, query, **kwargs):
            if query == "bad":
                raise RuntimeError("kuzu down")
            return await super().search_chunk_ids(query, **kwargs)

    graph = _BoomOnBad([{"kind": "fact", "uuid": "e1", "memory": "ok", "fact": "ok"}])
    memory = GraphitiConversationMemory(graph, default_top_k=8)
    tool = SearchMemoryTool(
        memory=memory,
        accumulator=Accumulator(),
        limits=RetrievalAgentLimits(),
        user_id=1,
        character_id="aria",
    )
    with patch("hirocli.services.memory.agent.search_tool.log.exception") as exc_log:
        result = await tool.call(
            _args(SearchMemoryQuery(query="bad"), SearchMemoryQuery(query="good"))
        )
    bad, good = result.sub_results
    assert bad.error is not None and "kuzu down" in bad.error
    assert bad.returned == 0
    assert good.error is None
    assert good.returned == 1
    exc_log.assert_called_once()


@pytest.mark.asyncio
async def test_hops_above_pref_max_clamped() -> None:
    tool = _tool(hits=[], limits=RetrievalAgentLimits(hops_max=2))
    await tool.call(_args(SearchMemoryQuery(query="linked entities", hops=3)))
    assert tool._memory._graph.search_calls[0]["k_hop"] == 2
