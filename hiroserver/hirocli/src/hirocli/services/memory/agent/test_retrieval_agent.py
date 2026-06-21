"""Tests for the bounded retrieval-agent loop (P3, refactored P9: multi-arg tool + turn cap)."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hirocli.domain.preferences import RetrievalAgentLimits
from hirocli.runtime.tests.graph_fakes import ScriptedChatModel, ai_text, ai_tool_call
from hirocli.services.memory.agent.retrieval_agent import run_retrieval
from hirocli.services.memory.graphiti_conversation import GraphitiConversationMemory

_PROMPT = "MAX={MAX_AGENT_TURNS} PAR={MAX_PARALLEL_SEARCHES} LIM={MAX_LIMIT}"


class _SlowFakeGraph:
    """Graph stub whose search sleeps so concurrent sub-query gather timing is observable."""

    observability = "ledger"

    def __init__(self, *, delay_s: float = 0.0, hits: list[dict] | None = None) -> None:
        self.delay_s = delay_s
        self._hits = list(hits or [])
        self.search_calls: list[dict] = []

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
        self.search_calls.append({"query": query, "num_results": num_results})
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        fact_rows = tuple(dict(h) for h in self._hits)
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


class _FailOnQueryGraph(_SlowFakeGraph):
    """Raises on one query so a single bad sub-query can be exercised."""

    def __init__(self, *, fail_query: str, hits: list[dict] | None = None) -> None:
        super().__init__(hits=hits)
        self.fail_query = fail_query

    async def search_chunk_ids(self, query, **kwargs):
        if query == self.fail_query:
            raise RuntimeError("simulated search failure")
        return await super().search_chunk_ids(query, **kwargs)


def _memory(*, graph: _SlowFakeGraph) -> GraphitiConversationMemory:
    return GraphitiConversationMemory(graph, default_top_k=8, temporal_default="current")


def _hit(uuid: str, text: str) -> dict:
    return {"kind": "fact", "uuid": uuid, "memory": text, "fact": text}


def _q(query: str, **knobs) -> dict:
    return {"query": query, "temporal": "current", "limit": 20, "hops": 1, "goal": "", **knobs}


def _search_call(*queries: dict, call_id: str = "c1"):
    return ai_tool_call("search_memory", {"queries": list(queries)}, call_id=call_id)


async def _run(*, model, memory, limits=None, question="Q?") -> object:
    return await run_retrieval(
        question=question,
        memory=memory,
        limits=limits or RetrievalAgentLimits(),
        prompt_text=_PROMPT,
        model=model,
        user_id=1,
        character_id="aria",
    )


@pytest.mark.asyncio
async def test_single_search_then_answer() -> None:
    graph = _SlowFakeGraph(hits=[_hit("e1", "Budget is $50")])
    model = ScriptedChatModel(
        responses=[_search_call(_q("monthly budget")), ai_text("The budget is $50.")]
    )
    result = await _run(model=model, memory=_memory(graph=graph))
    assert result.accumulator.size() == 1
    assert result.answer_text == "The budget is $50."
    assert result.reduce_op == "none"
    assert len(graph.search_calls) == 1


@pytest.mark.asyncio
async def test_decomposition_sub_queries_gathered_concurrently() -> None:
    graph = _SlowFakeGraph(delay_s=0.1, hits=[_hit("e1", "fact")])
    model = ScriptedChatModel(
        responses=[
            _search_call(_q("job"), _q("hobby"), _q("trip", temporal="all")),
            ai_text("job, hobby, trip"),
        ]
    )

    real_gather = asyncio.gather
    gather_widths: list[int] = []

    async def spy_gather(*coros, **kwargs):
        gather_widths.append(len(coros))
        return await real_gather(*coros, **kwargs)

    started = time.perf_counter()
    with patch("hirocli.services.memory.agent.search_tool.asyncio.gather", side_effect=spy_gather):
        result = await _run(
            model=model,
            memory=_memory(graph=graph),
            limits=RetrievalAgentLimits(max_parallel_searches=3),
        )
    elapsed = time.perf_counter() - started

    assert result.answer_text == "job, hobby, trip"
    assert gather_widths.count(3) == 1  # one tool call, three sub-queries gathered together
    assert len(graph.search_calls) == 3
    assert elapsed < 0.25


@pytest.mark.asyncio
async def test_caps_max_agent_turns() -> None:
    """With max_agent_turns=4 the model gets 3 search turns; turn 4 is forced final."""
    graph = _SlowFakeGraph(hits=[_hit("e1", "x")])
    model = ScriptedChatModel(
        responses=[
            _search_call(_q("q1"), call_id="c1"),
            _search_call(_q("q2"), call_id="c2"),
            _search_call(_q("q3"), call_id="c3"),
            ai_text("forced final"),
        ]
    )
    result = await _run(model=model, memory=_memory(graph=graph), limits=RetrievalAgentLimits(max_agent_turns=4))
    assert len(graph.search_calls) == 3
    assert result.answer_text == "forced final"
    assert model._cursor[0] == 4  # three search turns + one forced final


@pytest.mark.asyncio
async def test_agent_counter_advances_per_invocation() -> None:
    graph = _SlowFakeGraph(hits=[_hit("e1", "x")])
    model = ScriptedChatModel(responses=[_search_call(_q("q1")), ai_text("done")])
    result = await _run(model=model, memory=_memory(graph=graph))
    final = next(row for row in result.transcript if row["event"] == "final")
    assert final["cumulative_agent_turns"] == 2  # one search turn + one answer turn


@pytest.mark.asyncio
async def test_last_allowed_turn_strips_tools() -> None:
    """max_agent_turns=1 → the only turn is forced final; even a scripted tool call is ignored."""
    graph = _SlowFakeGraph(hits=[_hit("e1", "x")])
    model = ScriptedChatModel(responses=[_search_call(_q("q1")), ai_text("never reached")])
    result = await _run(model=model, memory=_memory(graph=graph), limits=RetrievalAgentLimits(max_agent_turns=1))
    assert graph.search_calls == []  # tools stripped on the forced turn → no search ran
    assert result.accumulator.size() == 0
    assert model._cursor[0] == 1


@pytest.mark.asyncio
async def test_parses_final_reduce_op() -> None:
    graph = _SlowFakeGraph(hits=[_hit("e1", "Budget changed")])
    model = ScriptedChatModel(
        responses=[
            _search_call(_q("budget history")),
            ai_text('{"reduce": {"op": "latest"}, "answer": "Latest budget is $50."}'),
        ]
    )
    result = await _run(model=model, memory=_memory(graph=graph))
    assert result.reduce_op == "latest"
    assert result.answer_text == "Latest budget is $50."


@pytest.mark.asyncio
async def test_no_tool_calls_returns_direct_answer() -> None:
    graph = _SlowFakeGraph()
    model = ScriptedChatModel(responses=[ai_text("No memory needed.")])
    result = await _run(model=model, memory=_memory(graph=graph))
    assert graph.search_calls == []
    assert result.answer_text == "No memory needed."
    assert result.accumulator.size() == 0


@pytest.mark.asyncio
async def test_trace_event_shapes() -> None:
    """A search turn yields tool_call + one sub_result per sub-query, then a final row."""
    graph = _SlowFakeGraph(hits=[_hit("e1", "Budget is $50")])
    model = ScriptedChatModel(
        responses=[_search_call(_q("monthly budget")), ai_text("The budget is $50.")]
    )
    result = await _run(model=model, memory=_memory(graph=graph))
    events = [row["event"] for row in result.transcript]
    assert events == ["tool_call", "sub_result", "final"]


@pytest.mark.asyncio
async def test_one_failing_sub_query_does_not_abort() -> None:
    graph = _FailOnQueryGraph(fail_query="bad", hits=[_hit("e1", "ok")])
    model = ScriptedChatModel(
        responses=[_search_call(_q("bad"), _q("good")), ai_text("Recovered.")]
    )
    result = await _run(model=model, memory=_memory(graph=graph))
    assert result.answer_text == "Recovered."
    sub_results = [row for row in result.transcript if row["event"] == "sub_result"]
    assert len(sub_results) == 2
    errored = [row for row in sub_results if row.get("error")]
    assert len(errored) == 1
    assert "simulated search failure" in errored[0]["error"]
