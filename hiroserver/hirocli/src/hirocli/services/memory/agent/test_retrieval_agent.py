"""Tests for the bounded retrieval-agent loop (P3; P9 multi-arg tool; P10 dedicated structured final).

P10: the loop runs a tool-bound SEARCH phase (``bind_tools``) for up to ``max_agent_turns - 1``
turns, then ONE tool-free structured turn (``with_structured_output``) yields the declared reduce
op + answer. ``ScriptedChatModel`` scripts the final turn via :func:`ai_final` (JSON content the
fake's ``with_structured_output`` parses).
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from hirocli.domain.preferences import RetrievalAgentLimits
from hirocli.runtime.tests.graph_fakes import ScriptedChatModel, ai_final, ai_text
from hirocli.services.memory.agent.retrieval_agent import _coerce_final, run_retrieval
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
    from hirocli.runtime.tests.graph_fakes import ai_tool_call

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
async def test_loop_llm_usage_attributed_to_ledger_entry(tmp_path) -> None:
    """The loop's own search + final LLM token usage must land on the active memory_recall entry.

    Regression guard for the agentic-cost fix: before it, run_retrieval drove its own LLM calls but
    never read usage_metadata, so the memory_recall node showed no model/tokens/cost ($0)."""
    from hirocli.runtime.agent_graph.ledger import LedgerSink, current_entry

    graph = _SlowFakeGraph(hits=[_hit("e1", "Budget is $50")])
    # search turn (in 8 / out 3) + stop turn (in 10 / out 5) + final turn (in 8 / out 4)
    # → totals in 26 / out 12, summed across all three LLM calls.
    model = ScriptedChatModel(
        responses=[
            _search_call(_q("monthly budget")),
            ai_text("done searching", input_tokens=10, output_tokens=5),
            ai_final("The budget is $50."),
        ]
    )

    sink = LedgerSink(tmp_path)
    entry = sink.open_entry(
        "memory_recall", {}, None, captures=frozenset({"usage", "decision"})
    )
    token = current_entry.set(entry)
    try:
        await run_retrieval(
            question="Q?",
            memory=_memory(graph=graph),
            limits=RetrievalAgentLimits(),
            prompt_text=_PROMPT,
            model=model,
            user_id=1,
            character_id="aria",
            model_id="openai:gpt-5.4",
        )
    finally:
        current_entry.reset(token)

    assert entry.model == "openai:gpt-5.4"
    assert entry.provider == "openai"
    assert entry.input_tokens == 26
    assert entry.output_tokens == 12


@pytest.mark.asyncio
async def test_verbatim_fallback_when_model_never_searches() -> None:
    """H3 floor: a model that emits zero searches must NOT recall nothing — one verbatim search
    with the raw question runs so recall is never worse than the pre-agentic single-shot baseline."""
    graph = _SlowFakeGraph(hits=[_hit("e1", "Budget is $50")])
    # No search call at all — straight to a final answer.
    model = ScriptedChatModel(responses=[ai_final("The budget is $50.")])
    result = await _run(model=model, memory=_memory(graph=graph), question="What's the budget?")
    # The verbatim fallback populated the accumulator from the raw question.
    assert result.accumulator.size() == 1
    assert len(graph.search_calls) == 1
    assert graph.search_calls[0]["query"] == "What's the budget?"
    fallback = [r for r in result.transcript if r.get("sub_queries") or r.get("event") == "sub_result"]
    assert fallback, "fallback search should appear in the transcript"


@pytest.mark.asyncio
async def test_verbatim_fallback_covers_max_agent_turns_one() -> None:
    """H3 config trap: max_agent_turns=1 leaves zero search turns — without the floor EVERY question
    would recall nothing. The verbatim fallback must still run."""
    graph = _SlowFakeGraph(hits=[_hit("e1", "fact")])
    model = ScriptedChatModel(responses=[ai_final("answer")])
    result = await _run(
        model=model,
        memory=_memory(graph=graph),
        limits=RetrievalAgentLimits(max_agent_turns=1),
        question="anything",
    )
    assert result.accumulator.size() == 1
    assert len(graph.search_calls) == 1


@pytest.mark.asyncio
async def test_no_verbatim_fallback_when_loop_already_recalled() -> None:
    """The floor must NOT fire when the loop already accumulated facts (no wasted extra search)."""
    graph = _SlowFakeGraph(hits=[_hit("e1", "Budget is $50")])
    model = ScriptedChatModel(
        responses=[_search_call(_q("monthly budget")), ai_final("The budget is $50.")]
    )
    result = await _run(model=model, memory=_memory(graph=graph))
    assert result.accumulator.size() == 1
    assert len(graph.search_calls) == 1  # the loop's one search only — no extra fallback search


@pytest.mark.asyncio
async def test_single_search_then_final() -> None:
    graph = _SlowFakeGraph(hits=[_hit("e1", "Budget is $50")])
    model = ScriptedChatModel(
        responses=[_search_call(_q("monthly budget")), ai_final("The budget is $50.")]
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
            ai_final("job, hobby, trip"),
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
async def test_caps_search_turns_then_final() -> None:
    """max_agent_turns=4 → 3 tool-bound search turns, then turn 4 is the dedicated structured final."""
    graph = _SlowFakeGraph(hits=[_hit("e1", "x")])
    model = ScriptedChatModel(
        responses=[
            _search_call(_q("q1"), call_id="c1"),
            _search_call(_q("q2"), call_id="c2"),
            _search_call(_q("q3"), call_id="c3"),
            ai_final("forced final"),
        ]
    )
    result = await _run(
        model=model, memory=_memory(graph=graph), limits=RetrievalAgentLimits(max_agent_turns=4)
    )
    assert len(graph.search_calls) == 3
    assert result.answer_text == "forced final"
    final = next(row for row in result.transcript if row["event"] == "final")
    assert final["cumulative_agent_turns"] == 4  # 3 search turns + the structured final


@pytest.mark.asyncio
async def test_counter_counts_search_stop_and_final() -> None:
    """Early stop: one search turn, one no-tool stop turn, then the structured final = 3 invocations."""
    graph = _SlowFakeGraph(hits=[_hit("e1", "x")])
    model = ScriptedChatModel(responses=[_search_call(_q("q1")), ai_text("done"), ai_final("answer")])
    result = await _run(model=model, memory=_memory(graph=graph))
    final = next(row for row in result.transcript if row["event"] == "final")
    assert final["cumulative_agent_turns"] == 3


@pytest.mark.asyncio
async def test_zero_search_turns_goes_straight_to_final() -> None:
    """max_agent_turns=1 → no model search budget; the verbatim fallback floor (H3) still runs one
    search so recall isn't empty, then the dedicated structured final turn answers."""
    graph = _SlowFakeGraph(hits=[_hit("e1", "x")])
    model = ScriptedChatModel(responses=[ai_final("only final")])
    result = await _run(
        model=model, memory=_memory(graph=graph), limits=RetrievalAgentLimits(max_agent_turns=1)
    )
    assert len(graph.search_calls) == 1  # the verbatim fallback (no model-driven search turn ran)
    assert graph.search_calls[0]["query"] == "Q?"
    assert result.accumulator.size() == 1
    assert result.answer_text == "only final"
    final = next(row for row in result.transcript if row["event"] == "final")
    assert final["cumulative_agent_turns"] == 1


@pytest.mark.asyncio
async def test_final_reduce_op_parsed() -> None:
    graph = _SlowFakeGraph(hits=[_hit("e1", "Budget changed")])
    model = ScriptedChatModel(
        responses=[_search_call(_q("budget history")), ai_final("Latest budget is $50.", op="latest")]
    )
    result = await _run(model=model, memory=_memory(graph=graph))
    assert result.reduce_op == "latest"
    assert result.answer_text == "Latest budget is $50."


@pytest.mark.asyncio
async def test_final_reduce_args_propagate() -> None:
    graph = _SlowFakeGraph(hits=[_hit("e1", "movies")])
    model = ScriptedChatModel(
        responses=[
            _search_call(_q("planned movies")),
            ai_final("13 movies", op="distinct_count", kind="edge"),
        ]
    )
    result = await _run(model=model, memory=_memory(graph=graph))
    assert result.reduce_op == "distinct_count"
    assert result.reduce_args == {"kind": "edge"}


@pytest.mark.asyncio
async def test_no_search_direct_final() -> None:
    graph = _SlowFakeGraph()  # no hits
    model = ScriptedChatModel(responses=[ai_final("No information available.")])
    result = await _run(model=model, memory=_memory(graph=graph))
    # The verbatim fallback (H3) still runs as a floor, but the empty graph yields nothing to recall.
    assert len(graph.search_calls) == 1
    assert result.answer_text == "No information available."
    assert result.accumulator.size() == 0


@pytest.mark.asyncio
async def test_trace_event_shapes() -> None:
    """A search turn yields tool_call + one sub_result per sub-query, then a final row."""
    graph = _SlowFakeGraph(hits=[_hit("e1", "Budget is $50")])
    model = ScriptedChatModel(
        responses=[_search_call(_q("monthly budget")), ai_final("The budget is $50.")]
    )
    result = await _run(model=model, memory=_memory(graph=graph))
    events = [row["event"] for row in result.transcript]
    assert events == ["tool_call", "sub_result", "final"]


@pytest.mark.asyncio
async def test_one_failing_sub_query_does_not_abort() -> None:
    graph = _FailOnQueryGraph(fail_query="bad", hits=[_hit("e1", "ok")])
    model = ScriptedChatModel(responses=[_search_call(_q("bad"), _q("good")), ai_final("Recovered.")])
    result = await _run(model=model, memory=_memory(graph=graph))
    assert result.answer_text == "Recovered."
    sub_results = [row for row in result.transcript if row["event"] == "sub_result"]
    assert len(sub_results) == 2
    errored = [row for row in sub_results if row.get("error")]
    assert len(errored) == 1
    assert "simulated search failure" in errored[0]["error"]


# --- _coerce_final: the provider-shape fallback paths (json_mode dict / parse failure) -----------


def test_coerce_final_from_json_mode_dict_nested_args() -> None:
    """DeepSeek json_mode returns a plain dict (not a RetrievalFinal). The model is instructed to
    nest op args under "args" — they must be read from there, not misread as args={"args": {...}}."""
    op, args, answer = _coerce_final(
        {"reduce": {"op": "distinct_count", "args": {"kind": "edge"}}, "answer": "3 movies"}, None
    )
    assert op == "distinct_count"
    assert args == {"kind": "edge"}
    assert answer == "3 movies"


def test_coerce_final_from_json_mode_dict_flat_args_tolerated() -> None:
    """Older inline shape (args as siblings of op) still degrades gracefully, not silently dropped."""
    op, args, answer = _coerce_final(
        {"reduce": {"op": "date_diff", "anchors": ["a", "b"]}, "answer": "5 days"}, None
    )
    assert op == "date_diff"
    assert args == {"anchors": ["a", "b"]}
    assert answer == "5 days"


def test_coerce_final_unknown_op_degrades_to_none() -> None:
    op, args, answer = _coerce_final({"reduce": {"op": "bogus"}, "answer": "x"}, None)
    assert op == "none"
    assert answer == "x"


def test_coerce_final_non_json_raw_becomes_answer() -> None:
    op, args, answer = _coerce_final(None, AIMessage(content="plain prose answer"))
    assert op == "none"
    assert args == {}
    assert answer == "plain prose answer"
