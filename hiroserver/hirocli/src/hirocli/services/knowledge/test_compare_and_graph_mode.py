"""Phase 5a — tests for ``KnowledgeService.compare`` + ``graph_mode`` Tool param.

Covers:

* ``service.compare()`` runs both legs (use_graph=False/True), returns a
  ``KnowledgeAnswerComparison`` with both results, and runs them **concurrently**
  (a sleep-based timing check confirms wall-clock ~= max, not sum).
* ``KnowledgeAnswerTool`` dispatches ``graph_mode="off"/"on"`` to
  ``service.answer(use_graph=…)`` and ``graph_mode="compare"`` to
  ``service.compare()``.
* Invalid ``graph_mode`` raises ``ValueError`` at the Tool boundary BEFORE any
  service resolution (cheap callers fail fast; no spurious workspace lookup).

Mocking strategy: a tiny in-process ``FakeService`` replaces
``KnowledgeService`` via ``monkeypatch`` of ``_resolve_service``. Avoids
spinning a real workspace + Qdrant + LangGraph for what is really a dispatch
test.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from hirocli.services.knowledge.models import (
    KnowledgeAnswerComparison,
    KnowledgeAnswerResult,
)
from hirocli.tools.knowledge import (
    GRAPH_MODE_COMPARE,
    GRAPH_MODE_OFF,
    GRAPH_MODE_ON,
    KnowledgeAnswerTool,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeService:
    """Minimal stand-in for KnowledgeService.

    Records every ``answer`` call (so we can assert *what* was dispatched) and
    optionally sleeps per call (so the concurrency test has timing to measure).
    Implements ``compare`` by calling ``answer`` twice via ``asyncio.gather``
    — same logic the real service uses, so the dispatch test stays meaningful.
    """

    def __init__(self, *, sleep_per_call: float = 0.0):
        self.answer_calls: list[dict] = []
        self.compare_calls: list[dict] = []
        self._sleep = sleep_per_call
        self.closed = False

    async def answer(self, query, **kwargs):
        self.answer_calls.append({"query": query, **kwargs})
        if self._sleep:
            await asyncio.sleep(self._sleep)
        graph_on = kwargs.get("graph_mode") in ("graphiti", "mix")
        return KnowledgeAnswerResult(
            query=query,
            answer=f"{'graph' if graph_on else 'flat'} answer for {query!r}",
            sources=[],
            elapsed_ms=int(self._sleep * 1000),
            no_results=False,
        )

    async def compare(self, query, **kwargs):
        self.compare_calls.append({"query": query, **kwargs})
        t0 = time.perf_counter()
        flat, graph = await asyncio.gather(
            self.answer(query, **{**kwargs, "graph_mode": "off"}),
            self.answer(query, **{**kwargs, "graph_mode": "mix"}),
        )
        return KnowledgeAnswerComparison(
            query=query,
            flat=flat,
            graph=graph,
            elapsed_ms=int((time.perf_counter() - t0) * 1000),
        )

    async def close(self):
        self.closed = True


@pytest.fixture
def injected_service(monkeypatch):
    """Replace ``_resolve_service`` so any Tool call lands on our FakeService."""

    def _factory(sleep_per_call: float = 0.0) -> FakeService:
        fake = FakeService(sleep_per_call=sleep_per_call)
        monkeypatch.setattr(
            "hirocli.tools.knowledge._resolve_service",
            lambda runtime, workspace: (fake, False),  # owned=False → no close-on-exit
        )
        return fake

    return _factory


# ---------------------------------------------------------------------------
# Service.compare — direct behavior + concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_returns_both_legs_in_comparison_shape() -> None:
    fake = FakeService()
    result = await fake.compare("test question", rewrite=True)
    assert isinstance(result, KnowledgeAnswerComparison)
    assert result.query == "test question"
    assert result.flat.answer.startswith("flat ")
    assert result.graph.answer.startswith("graph ")
    # answer() was invoked twice — once per leg
    assert len(fake.answer_calls) == 2
    graph_modes = sorted(call["graph_mode"] for call in fake.answer_calls)
    assert graph_modes == ["mix", "off"]


@pytest.mark.asyncio
async def test_compare_passes_through_filters_and_tuning_to_both_legs() -> None:
    """Each leg must see the SAME query/filters/top_k/min_score/rewrite —
    only ``use_graph`` differs. Catches a future bug where compare diverges
    on a knob between the two legs (silent unfair comparison)."""
    fake = FakeService()
    filters = {"tags": ["_l3_eval_synthetic"]}
    await fake.compare(
        "q",
        top_k=15,
        min_score=0.1,
        filters=filters,
        rewrite=True,
        explain=True,
    )
    for call in fake.answer_calls:
        assert call["top_k"] == 15
        assert call["min_score"] == 0.1
        assert call["filters"] is filters
        assert call["rewrite"] is True
        assert call["explain"] is True


@pytest.mark.asyncio
async def test_compare_runs_legs_concurrently_not_serially() -> None:
    """Each leg sleeps 200ms. Serial would total ~400ms; concurrent ~200ms.
    Use 1.6x as the gate to allow CI noise but catch genuine serial regression."""
    fake = FakeService(sleep_per_call=0.2)
    t0 = time.perf_counter()
    await fake.compare("q", rewrite=True)
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.32, (
        f"compare ran legs serially ({elapsed:.3f}s) — should be ~0.2s concurrent"
    )


# ---------------------------------------------------------------------------
# Tool dispatch — graph_mode handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_graph_mode_off_calls_answer_with_use_graph_false(
    injected_service,
) -> None:
    fake = injected_service()
    tool = KnowledgeAnswerTool()
    result = await tool.execute_async(query="q", rewrite=True, graph_mode=GRAPH_MODE_OFF)
    assert isinstance(result, KnowledgeAnswerResult)
    assert len(fake.answer_calls) == 1
    assert fake.answer_calls[0]["graph_mode"] == "off"
    assert fake.compare_calls == []


@pytest.mark.asyncio
async def test_tool_graph_mode_on_calls_answer_with_use_graph_true(
    injected_service,
) -> None:
    fake = injected_service()
    tool = KnowledgeAnswerTool()
    result = await tool.execute_async(query="q", rewrite=True, graph_mode=GRAPH_MODE_ON)
    assert isinstance(result, KnowledgeAnswerResult)
    assert len(fake.answer_calls) == 1
    # Ask tab's "on" maps to the fused "mix" leg.
    assert fake.answer_calls[0]["graph_mode"] == "mix"


@pytest.mark.asyncio
async def test_tool_graph_mode_compare_calls_compare(injected_service) -> None:
    fake = injected_service()
    tool = KnowledgeAnswerTool()
    result = await tool.execute_async(
        query="what does my sister's husband do?",
        rewrite=True,
        graph_mode=GRAPH_MODE_COMPARE,
    )
    assert isinstance(result, KnowledgeAnswerComparison)
    assert result.query == "what does my sister's husband do?"
    # compare was called exactly once; it internally called answer twice
    assert len(fake.compare_calls) == 1
    assert len(fake.answer_calls) == 2


@pytest.mark.asyncio
async def test_tool_graph_mode_default_is_off(injected_service) -> None:
    """Default behavior preserves today's flat-RAG surface (no L3 effect unless
    the caller opts in). Catches a regression that silently flips the default."""
    fake = injected_service()
    tool = KnowledgeAnswerTool()
    result = await tool.execute_async(query="q", rewrite=True)  # no graph_mode
    assert isinstance(result, KnowledgeAnswerResult)
    assert fake.answer_calls[0]["graph_mode"] == "off"


@pytest.mark.asyncio
async def test_tool_graph_mode_normalizes_case_and_whitespace(
    injected_service,
) -> None:
    """Real CLI input may have stray casing/whitespace; don't make callers
    pre-normalize."""
    fake = injected_service()
    tool = KnowledgeAnswerTool()
    await tool.execute_async(query="q", graph_mode="  COMPARE  ")
    assert len(fake.compare_calls) == 1


@pytest.mark.asyncio
async def test_tool_invalid_graph_mode_raises_before_service_resolution(
    monkeypatch,
) -> None:
    """Validation MUST happen before _resolve_service runs (so a bad mode is a
    fast-fail with a clear error, not a workspace-lookup failure)."""
    resolved: list[int] = []

    def boom(runtime, workspace):
        resolved.append(1)
        raise RuntimeError("should not get here")

    monkeypatch.setattr("hirocli.tools.knowledge._resolve_service", boom)
    tool = KnowledgeAnswerTool()
    with pytest.raises(ValueError, match="graph_mode must be one of"):
        await tool.execute_async(query="q", graph_mode="bogus")
    assert resolved == []


@pytest.mark.asyncio
async def test_tool_invalid_graph_mode_message_lists_valid_values(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "hirocli.tools.knowledge._resolve_service",
        lambda runtime, workspace: (FakeService(), False),
    )
    tool = KnowledgeAnswerTool()
    with pytest.raises(ValueError) as exc_info:
        await tool.execute_async(query="q", graph_mode="grpah")  # typo
    msg = str(exc_info.value)
    # Message contains the valid set — actionable for the caller.
    assert "off" in msg and "on" in msg and "compare" in msg


# ---------------------------------------------------------------------------
# Tool dispatch — graph_temporal per-query override (§7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_graph_temporal_threads_into_answer(injected_service) -> None:
    """The per-query temporal override reaches service.answer (was dead plumbing)."""
    fake = injected_service()
    tool = KnowledgeAnswerTool()
    await tool.execute_async(
        query="where did Adam live before?", rewrite=True, graph_mode=GRAPH_MODE_ON,
        graph_temporal="all",
    )
    assert fake.answer_calls[0]["graph_temporal"] == "all"


@pytest.mark.asyncio
async def test_tool_graph_temporal_threads_into_compare(injected_service) -> None:
    fake = injected_service()
    tool = KnowledgeAnswerTool()
    await tool.execute_async(
        query="q", rewrite=True, graph_mode=GRAPH_MODE_COMPARE, graph_temporal="current",
    )
    assert fake.compare_calls[0]["graph_temporal"] == "current"


@pytest.mark.asyncio
async def test_tool_graph_temporal_default_is_none(injected_service) -> None:
    """Omitted → None so service.answer falls back to the admin temporal_default pref."""
    fake = injected_service()
    tool = KnowledgeAnswerTool()
    await tool.execute_async(query="q", rewrite=True, graph_mode=GRAPH_MODE_ON)
    assert fake.answer_calls[0]["graph_temporal"] is None


@pytest.mark.asyncio
async def test_tool_invalid_graph_temporal_raises(injected_service) -> None:
    fake = injected_service()
    tool = KnowledgeAnswerTool()
    with pytest.raises(ValueError, match="graph_temporal must be one of"):
        await tool.execute_async(query="q", graph_mode=GRAPH_MODE_ON, graph_temporal="yesterday")
    assert fake.answer_calls == []
