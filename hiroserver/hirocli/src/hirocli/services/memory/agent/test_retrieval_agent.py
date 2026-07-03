"""Tests for the bounded retrieval-agent loop (P3; P9 multi-arg tool).

Reduce removed (2026-06): the loop runs a tool-bound SEARCH phase (``bind_tools``) and ends two
ways — exit A (the model emits a no-tool turn whose content IS the answer, reused with no extra
call) or exit B (the turn budget is exhausted while still searching, so ONE tool-free
``_final_answer_turn`` composes the answer). ``ScriptedChatModel`` replays responses in order across
both the bound search turns and the unbound final turn (shared cursor); :func:`ai_final` is a plain
answer reply, :func:`ai_text` a plain no-tool turn.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import PrivateAttr

from hirocli.domain.preferences import RetrievalAgentLimits
from hirocli.runtime.tests.graph_fakes import ScriptedChatModel, ai_final, ai_text
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
    return GraphitiConversationMemory(graph, temporal_default="current")


def _hit(uuid: str, text: str) -> dict:
    return {"kind": "fact", "uuid": uuid, "memory": text, "fact": text}


def _q(query: str, **knobs) -> dict:
    return {"query": query, "temporal": "current", "limit": 20, "hops": 1, "goal": "", **knobs}


def _search_call(*queries: dict, call_id: str = "c1"):
    from hirocli.runtime.tests.graph_fakes import ai_tool_call

    return ai_tool_call("search_memory", {"queries": list(queries)}, call_id=call_id)


async def _run(*, model, memory, limits=None, question="Q?", allow_abstain=False, history=None) -> object:
    return await run_retrieval(
        question=question,
        memory=memory,
        limits=limits or RetrievalAgentLimits(),
        prompt_text=_PROMPT,
        model=model,
        user_id=1,
        character_id="aria",
        allow_abstain=allow_abstain,
        history=history,
    )


@pytest.mark.asyncio
async def test_loop_llm_usage_attributed_to_ledger_entry(tmp_path) -> None:
    """The loop's own search + answer LLM token usage must land on the active memory_recall entry.
    Exercised across 4 LLM calls (3 search turns + the answer turn) so both search-turn and
    answer-turn usage folding are covered.

    Regression guard for the agentic-cost fix: before it, run_retrieval drove its own LLM calls but
    never read usage_metadata, so the memory_recall node showed no model/tokens/cost ($0)."""
    from hirocli.runtime.agent_graph.ledger import LedgerSink, current_entry

    graph = _SlowFakeGraph(hits=[_hit("e1", "Budget is $50")])
    # 3 search turns (in 8 / out 3 each) + the answer turn (in 8 / out 4)
    # → totals in 32 / out 13, summed across all four LLM calls.
    model = ScriptedChatModel(
        responses=[
            _search_call(_q("q1"), call_id="c1"),
            _search_call(_q("q2"), call_id="c2"),
            _search_call(_q("q3"), call_id="c3"),
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
            limits=RetrievalAgentLimits(max_agent_turns=4),
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
    assert entry.input_tokens == 32
    assert entry.output_tokens == 13


@pytest.mark.asyncio
async def test_verbatim_fallback_when_model_never_searches() -> None:
    """H3 floor: a model that emits zero searches must NOT recall nothing — one verbatim search
    with the raw question runs so recall is never worse than the pre-agentic single-shot baseline."""
    graph = _SlowFakeGraph(hits=[_hit("e1", "Budget is $50")])
    # No search call: a no-tool stop turn (groundless — acc empty), then the exit-B answer turn.
    model = ScriptedChatModel(responses=[ai_text("Let me answer."), ai_final("The budget is $50.")])
    result = await _run(model=model, memory=_memory(graph=graph), question="What's the budget?")
    # The verbatim fallback populated the accumulator from the raw question.
    assert result.accumulator.size() == 1
    assert len(graph.search_calls) == 1
    assert graph.search_calls[0]["query"] == "What's the budget?"
    assert result.answer_text == "The budget is $50."
    fallback = [r for r in result.transcript if r.get("sub_queries") or r.get("event") == "sub_result"]
    assert fallback, "fallback search should appear in the transcript"


@pytest.mark.asyncio
async def test_max_agent_turns_one_grants_one_real_search_turn() -> None:
    """Regression for the turns=1 starvation (M3 fix, 2026-07-03): ``max_agent_turns`` now == the
    search-turn budget, so max_agent_turns=1 grants ONE real search turn (previously ZERO — every
    turns=1 recall could only fall back / abstain). The model searches on its one turn, then the
    exit-B compose turn answers over what it found — no verbatim fallback, because the loop recalled."""
    graph = _SlowFakeGraph(hits=[_hit("e1", "Budget is $50")])
    model = ScriptedChatModel(responses=[_search_call(_q("budget")), ai_final("The budget is $50.")])
    result = await _run(
        model=model,
        memory=_memory(graph=graph),
        limits=RetrievalAgentLimits(max_agent_turns=1),
        question="What's the budget?",
    )
    assert len(graph.search_calls) == 1  # the MODEL's own search turn, not a fallback
    assert graph.search_calls[0]["query"] == "budget"  # its query, not the raw question
    assert result.accumulator.size() == 1
    assert result.answer_text == "The budget is $50."


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
async def test_exit_a_reuses_stop_turn_no_extra_call() -> None:
    """Exit A: search, then a no-tool stop turn whose content IS the answer — reused directly, with
    NO extra model call (the stop turn = 2 invocations total, no forced final turn)."""
    graph = _SlowFakeGraph(hits=[_hit("e1", "Budget is $50")])
    model = ScriptedChatModel(
        responses=[_search_call(_q("monthly budget")), ai_final("The budget is $50.")]
    )
    result = await _run(model=model, memory=_memory(graph=graph))
    assert result.accumulator.size() == 1
    assert result.answer_text == "The budget is $50."
    assert len(graph.search_calls) == 1
    final = next(row for row in result.transcript if row["event"] == "final")
    assert final["cumulative_agent_turns"] == 2  # search turn + the stop turn (no separate final)


@pytest.mark.asyncio
async def test_exit_a_reuses_block_content_stop_turn() -> None:
    """Provider parity: Gemini/Anthropic return the stop turn's content as a LIST of blocks
    ([{"type":"text","text":...}]). Exit A must flatten and reuse it — a str-only guard regressed
    this to forcing the exit-B answer turn on EVERY question (a duplicate answer call)."""
    from langchain_core.messages import AIMessage

    graph = _SlowFakeGraph(hits=[_hit("e1", "Budget is $50")])
    block_stop = AIMessage(
        content=[{"type": "text", "text": "The budget is $50."}],
        usage_metadata={"input_tokens": 8, "output_tokens": 4, "total_tokens": 12},
    )
    model = ScriptedChatModel(responses=[_search_call(_q("monthly budget")), block_stop])
    result = await _run(model=model, memory=_memory(graph=graph))
    assert result.answer_text == "The budget is $50."  # flattened from blocks, reused
    assert len(graph.search_calls) == 1
    final = next(row for row in result.transcript if row["event"] == "final")
    assert final["cumulative_agent_turns"] == 2  # search + stop only — NO forced final turn


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
async def test_exit_b_caps_search_turns_then_forces_answer_turn() -> None:
    """Exit B: max_agent_turns=4 → the model searches all 4 tool-bound turns (never stops), then ONE
    forced tool-free answer turn composes the answer. The compose turn is NOT counted as a search
    turn, so the counter tops out at exactly 4 (not 5)."""
    graph = _SlowFakeGraph(hits=[_hit("e1", "x")])
    model = ScriptedChatModel(
        responses=[
            _search_call(_q("q1"), call_id="c1"),
            _search_call(_q("q2"), call_id="c2"),
            _search_call(_q("q3"), call_id="c3"),
            _search_call(_q("q4"), call_id="c4"),
            ai_final("forced final"),
        ]
    )
    result = await _run(
        model=model, memory=_memory(graph=graph), limits=RetrievalAgentLimits(max_agent_turns=4)
    )
    assert len(graph.search_calls) == 4
    assert result.answer_text == "forced final"
    final = next(row for row in result.transcript if row["event"] == "final")
    assert final["cumulative_agent_turns"] == 4  # 4 search turns; the forced compose turn isn't counted


@pytest.mark.asyncio
async def test_exit_a_counter_counts_search_and_stop_only() -> None:
    """Exit A early stop: one search turn + one no-tool stop turn = 2 invocations, no forced final."""
    graph = _SlowFakeGraph(hits=[_hit("e1", "x")])
    model = ScriptedChatModel(responses=[_search_call(_q("q1")), ai_text("done")])
    result = await _run(model=model, memory=_memory(graph=graph))
    assert result.answer_text == "done"
    final = next(row for row in result.transcript if row["event"] == "final")
    assert final["cumulative_agent_turns"] == 2


@pytest.mark.asyncio
async def test_turns_one_floor_when_model_skips_its_search_turn() -> None:
    """max_agent_turns=1 grants one search turn, but if the model spends it answering WITHOUT
    searching, the accumulator is empty → the verbatim-fallback floor (H3) still runs one search
    (raw question) and the forced tool-free answer turn composes. The compose turn isn't counted, so
    the counter stays at 1 (the single search-or-stop turn)."""
    graph = _SlowFakeGraph(hits=[_hit("e1", "x")])
    model = ScriptedChatModel(responses=[ai_text("answering directly"), ai_final("only final")])
    result = await _run(
        model=model, memory=_memory(graph=graph), limits=RetrievalAgentLimits(max_agent_turns=1)
    )
    assert len(graph.search_calls) == 1  # the verbatim fallback (the model didn't search)
    assert graph.search_calls[0]["query"] == "Q?"
    assert result.accumulator.size() == 1
    assert result.answer_text == "only final"
    final = next(row for row in result.transcript if row["event"] == "final")
    assert final["cumulative_agent_turns"] == 1


@pytest.mark.asyncio
async def test_no_search_direct_answer_empty_graph() -> None:
    graph = _SlowFakeGraph()  # no hits
    model = ScriptedChatModel(responses=[ai_text("nothing found"), ai_final("No information available.")])
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


# --- Phase 0 surface flags (history + allow_abstain) ------------------------------------------


class _RecordingChatModel(ScriptedChatModel):
    """``ScriptedChatModel`` that snapshots each turn's messages so history seeding is observable."""

    _seen: list = PrivateAttr(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        self._seen.append(list(messages))
        return super()._generate(messages, stop, run_manager, **kwargs)


@pytest.mark.asyncio
async def test_allow_abstain_skips_fallback_when_model_never_searches() -> None:
    """Phase 0 chat flag: with allow_abstain=True a loop that recalled NOTHING returns an empty
    draft — no verbatim fallback, no forced answer turn (persona answers without memory). Contrast
    the default (allow_abstain=False) path in test_verbatim_fallback_when_model_never_searches."""
    graph = _SlowFakeGraph()  # no hits
    # A no-tool stop turn (acc stays empty). The 2nd response is scripted to prove a forced final
    # turn does NOT run under abstain — if it did, answer_text would become "should not run".
    model = ScriptedChatModel(responses=[ai_text("no recall needed"), ai_final("should not run")])
    result = await _run(model=model, memory=_memory(graph=graph), allow_abstain=True, question="hi")
    assert result.answer_text == ""
    assert result.accumulator.size() == 0
    assert graph.search_calls == []  # verbatim fallback did NOT run


@pytest.mark.asyncio
async def test_allow_abstain_after_fruitless_search_returns_empty() -> None:
    """Abstain also covers the realistic chat case: the model DID search but the graph returned
    nothing — still no verbatim fallback, still an empty draft."""
    graph = _SlowFakeGraph()  # search runs but yields no hits
    model = ScriptedChatModel(responses=[_search_call(_q("anything")), ai_text("nothing found")])
    result = await _run(model=model, memory=_memory(graph=graph), allow_abstain=True)
    assert result.answer_text == ""
    assert result.accumulator.size() == 0
    assert len(graph.search_calls) == 1  # only the model's own search — no extra verbatim fallback


@pytest.mark.asyncio
async def test_history_seeded_between_system_prompt_and_question() -> None:
    """Phase 0: history is inserted AFTER the system prompt and BEFORE the question, so turn 1 sees
    recent context (default history=None keeps the plain system+question pair — covered elsewhere)."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    graph = _SlowFakeGraph(hits=[_hit("e1", "x")])
    model = _RecordingChatModel(responses=[_search_call(_q("q1")), ai_final("done")])
    history = [HumanMessage(content="my dog is Rex"), AIMessage(content="nice")]
    await _run(model=model, memory=_memory(graph=graph), history=history)

    first_call = model._seen[0]
    contents = [getattr(m, "content", None) for m in first_call]
    assert isinstance(first_call[0], SystemMessage)  # system prompt still leads
    assert first_call[-1].content == "Q?"  # question is last
    assert contents.index("my dog is Rex") < contents.index("nice") < contents.index("Q?")


@pytest.mark.asyncio
async def test_identities_substitute_into_prompt() -> None:
    """Identity threading: USER_NAME / AGENT_NAME fill the prompt so the loop phrases queries with the
    real names; blank falls back to generic wording (today's behavior)."""
    graph = _SlowFakeGraph(hits=[_hit("e1", "x")])
    model = _RecordingChatModel(responses=[_search_call(_q("q1")), ai_final("done")])
    await run_retrieval(
        question="Q?",
        memory=_memory(graph=graph),
        limits=RetrievalAgentLimits(),
        prompt_text="user={USER_NAME} · agent={AGENT_NAME}",
        model=model,
        user_id=1,
        character_id="aria",
        user_name="Misho",
        agent_name="Aria",
    )
    assert model._seen[0][0].content == "user=Misho · agent=Aria"

    blank = _RecordingChatModel(responses=[_search_call(_q("q1")), ai_final("done")])
    await run_retrieval(
        question="Q?",
        memory=_memory(graph=graph),
        limits=RetrievalAgentLimits(),
        prompt_text="user={USER_NAME} · agent={AGENT_NAME}",
        model=blank,
        user_id=1,
        character_id="aria",
    )
    assert blank._seen[0][0].content == "user=the user · agent=the assistant"
