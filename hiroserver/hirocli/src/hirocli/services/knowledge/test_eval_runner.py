"""Phase 5c — tests for the in-process eval runner + scoring module.

Two halves:

1. **eval_scoring** — pure-logic checks (mirror the tests in
   ``eval/test_l3_synthetic_eval.py`` so this package-side module is locked
   down independently of the standalone harness).
2. **eval_runner** — the orchestrator, with a fake service so we don't need a
   real LLM or workspace. Verifies it publishes the right events in order,
   computes the right summary, and that the gate fires correctly.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from hirocli.domain.events import DomainEvent, get_domain_event_bus
from hirocli.services.knowledge.constants import (
    KNOWLEDGE_EVAL_COMPLETED,
    KNOWLEDGE_EVAL_FAILED,
    KNOWLEDGE_EVAL_QUESTION_COMPLETED,
    KNOWLEDGE_EVAL_STARTED,
)
from hirocli.services.knowledge.eval_runner import (
    EVAL_SYNTHETIC_TAG,
    QuestionResult,
    load_questions,
    run_eval,
)
from hirocli.services.knowledge.eval_scoring import (
    MARK_ABSTAIN,
    MARK_FAIL,
    MARK_PARTIAL,
    MARK_PASS,
    MARK_RANK,
    Score,
    delta_mark,
    score_answer,
)
from hirocli.services.knowledge.models import (
    KnowledgeAnswerComparison,
    KnowledgeAnswerResult,
)


# ===========================================================================
# eval_scoring — pure-logic regressions
# ===========================================================================


def test_score_all_fragments_present_is_pass() -> None:
    s = score_answer("Omar works at Acme.", ["Omar", "Acme"], no_results=False)
    assert s.mark == MARK_PASS and s.found == 2


def test_score_some_fragments_is_partial() -> None:
    s = score_answer("Omar.", ["Omar", "Acme"], no_results=False)
    assert s.mark == MARK_PARTIAL


def test_score_no_fragments_is_fail() -> None:
    s = score_answer("dunno", ["Omar"], no_results=False)
    assert s.mark == MARK_FAIL


def test_score_case_insensitive() -> None:
    assert score_answer("OMAR at ACME.", ["Omar", "Acme"], no_results=False).mark == MARK_PASS


def test_score_no_results_with_expected_is_fail() -> None:
    assert score_answer("", ["Omar"], no_results=True).mark == MARK_FAIL


def test_score_negative_control_abstain_wins() -> None:
    assert score_answer("", [], no_results=True).mark == MARK_ABSTAIN
    assert score_answer("", [], no_results=False).mark == MARK_ABSTAIN  # empty answer counts


def test_score_negative_control_confident_answer_is_hallucination() -> None:
    s = score_answer("Paris.", [], no_results=False)
    assert s.mark == MARK_FAIL and s.label == "hallucinated"


def _score(mark: str) -> Score:
    return Score(mark=mark, label="x", found=0, expected=0)


def test_delta_mark_signs() -> None:
    assert delta_mark(_score(MARK_FAIL), _score(MARK_PASS)) == "+3"
    assert delta_mark(_score(MARK_PASS), _score(MARK_FAIL)) == "-3"
    assert delta_mark(_score(MARK_PASS), _score(MARK_PASS)) == "0"
    assert delta_mark(_score(MARK_FAIL), _score(MARK_ABSTAIN)) == "+1"


def test_mark_rank_orders_abstain_above_fail_below_partial() -> None:
    """Lock in the ordering — abstain is a 'safe' outcome, partial is better,
    pass is the goal."""
    assert MARK_RANK[MARK_FAIL] < MARK_RANK[MARK_ABSTAIN] < MARK_RANK[MARK_PARTIAL] < MARK_RANK[MARK_PASS]


# ===========================================================================
# load_questions — YAML parsing + validation
# ===========================================================================


def test_load_questions_default_path_works() -> None:
    qs = load_questions()
    assert isinstance(qs, list) and len(qs) >= 8
    for q in qs:
        assert q["id"] and q["question"]
        assert isinstance(q["expected_fragments"], list)


def test_load_questions_custom_path_rejects_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_questions(tmp_path / "nope.yaml")


def test_load_questions_rejects_missing_fragments_key(tmp_path: Path) -> None:
    p = tmp_path / "q.yaml"
    p.write_text(
        yaml.safe_dump([{"id": "x", "question": "hi"}]),  # missing expected_fragments
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="expected_fragments"):
        load_questions(p)


def test_load_questions_rejects_empty_list(tmp_path: Path) -> None:
    p = tmp_path / "q.yaml"
    p.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty list"):
        load_questions(p)


# ===========================================================================
# run_eval — fake service + event bus capture
# ===========================================================================


@dataclass
class FakeAnswerResult:
    answer: str
    no_results: bool = False
    elapsed_ms: int = 5


class FakeService:
    """Compare returns canned (flat, graph) answers based on the question id
    so each scenario maps cleanly to a row in the scoring table."""

    def __init__(self, *, script: dict[str, tuple[str, str]]):
        # qid → (flat_answer, graph_answer)
        self._script = script
        self.compare_calls: list[dict[str, Any]] = []

    async def compare(self, query, *, top_k=None, min_score=None,
                       filters=None, workspace_id=None, explain=False, rewrite=False):
        self.compare_calls.append({
            "query": query, "filters": filters, "rewrite": rewrite,
            "top_k": top_k, "min_score": min_score,
        })
        # Find the matching script entry by exact question text.
        flat_ans, graph_ans = self._script.get(query, ("", ""))
        return KnowledgeAnswerComparison(
            query=query,
            flat=KnowledgeAnswerResult(
                query=query, answer=flat_ans, sources=[], elapsed_ms=10,
                no_results=(flat_ans == ""),
            ),
            graph=KnowledgeAnswerResult(
                query=query, answer=graph_ans, sources=[], elapsed_ms=20,
                no_results=(graph_ans == ""),
            ),
            elapsed_ms=30,
        )


@pytest.fixture
def bus_with_loop():
    """Attach the running loop + capture events. Mirrors the existing pattern
    from test_credential_store.py."""
    bus = get_domain_event_bus()
    bus.reset()
    bus.attach_loop(asyncio.get_event_loop_policy().get_event_loop())  # outer loop
    captured: list[DomainEvent] = []

    async def handler(event: DomainEvent) -> None:
        captured.append(event)

    yield bus, handler, captured
    bus.reset()


@pytest.fixture
def event_capture(monkeypatch):
    """Capture events synchronously by intercepting bus.publish — simpler than
    going through the async dispatch path (which schedules via call_soon)."""
    bus = get_domain_event_bus()
    captured: list[DomainEvent] = []
    real_publish = bus.publish

    def capturing_publish(event: DomainEvent) -> None:
        captured.append(event)

    monkeypatch.setattr(bus, "publish", capturing_publish)
    yield captured
    monkeypatch.setattr(bus, "publish", real_publish)


def _q(id_: str, q: str, *, expected: list[str], requires_graph: bool = False) -> dict:
    return {
        "id": id_,
        "category": "test",
        "question": q,
        "expected_fragments": expected,
        "requires_graph": requires_graph,
    }


@pytest.mark.asyncio
async def test_run_eval_publishes_started_per_question_and_completed_in_order(
    event_capture, tmp_path
) -> None:
    """The Eval Batch UI relies on a deterministic event sequence:
    1 started · N×question_completed · 1 completed."""
    questions = [
        _q("a", "Q1?", expected=["foo"], requires_graph=True),
        _q("b", "Q2?", expected=["bar"]),
    ]
    fake = FakeService(script={
        "Q1?": ("", "foo answer"),     # flat fails, graph passes — graph win
        "Q2?": ("bar yes", "bar yes"), # both pass — tie
    })

    summary = await run_eval(fake, tmp_path, questions=questions, run_id="rid-1")

    types = [e.type for e in event_capture]
    assert types == [
        KNOWLEDGE_EVAL_STARTED,
        KNOWLEDGE_EVAL_QUESTION_COMPLETED,
        KNOWLEDGE_EVAL_QUESTION_COMPLETED,
        KNOWLEDGE_EVAL_COMPLETED,
    ]
    # Started payload
    assert event_capture[0].payload["run_id"] == "rid-1"
    assert event_capture[0].payload["total_questions"] == 2
    # Question events carry index/total/marks
    qc1 = event_capture[1].payload
    assert qc1["index"] == 0 and qc1["total"] == 2 and qc1["id"] == "a"
    assert qc1["flat"]["mark"] == MARK_FAIL
    assert qc1["graph"]["mark"] == MARK_PASS
    assert qc1["delta"] == "+3"
    # Summary payload matches what run_eval returned
    completed_payload = event_capture[-1].payload
    assert completed_payload["run_id"] == "rid-1"
    assert completed_payload["graph_wins"] == 1
    assert completed_payload["ties"] == 1
    assert summary.gate == "proceed"


@pytest.mark.asyncio
async def test_run_eval_default_filters_scope_to_synthetic_tag(
    event_capture, tmp_path
) -> None:
    """When the caller doesn't pass filters, the runner scopes retrieval to
    the eval tag so unrelated workspace docs don't pollute the comparison."""
    fake = FakeService(script={"Q?": ("ok", "ok")})
    questions = [_q("only", "Q?", expected=["ok"])]
    await run_eval(fake, tmp_path, questions=questions)

    assert len(fake.compare_calls) == 1
    assert fake.compare_calls[0]["filters"]["tags"] == [EVAL_SYNTHETIC_TAG]


@pytest.mark.asyncio
async def test_run_eval_passes_through_caller_filters(event_capture, tmp_path) -> None:
    """Caller-supplied filters override the default tag scope (e.g. a tester
    wants to compare across the full workspace)."""
    fake = FakeService(script={"Q?": ("ok", "ok")})
    custom = {"tags": ["custom_tag"], "owner_kind": "system"}
    await run_eval(fake, tmp_path, questions=[_q("x", "Q?", expected=["ok"])], filters=custom)
    assert fake.compare_calls[0]["filters"] == custom


@pytest.mark.asyncio
async def test_gate_pivots_when_graph_does_not_beat_flat_on_required_subset(
    event_capture, tmp_path
) -> None:
    """Strict gate: parity counts as PIVOT, not PROCEED. Locks in the
    "graph must measurably win" rule."""
    questions = [
        _q("r1", "Q1?", expected=["a"], requires_graph=True),
        _q("r2", "Q2?", expected=["b"], requires_graph=True),
    ]
    fake = FakeService(script={
        "Q1?": ("a yes", "a yes"),  # tie
        "Q2?": ("b yes", "b yes"),  # tie
    })
    summary = await run_eval(fake, tmp_path, questions=questions)
    assert summary.gate == "pivot"
    assert summary.requires_graph_graph_passing == summary.requires_graph_flat_passing


@pytest.mark.asyncio
async def test_gate_proceeds_when_graph_strictly_beats_flat_on_required_subset(
    event_capture, tmp_path
) -> None:
    questions = [
        _q("r1", "Q1?", expected=["a"], requires_graph=True),
        _q("r2", "Q2?", expected=["b"], requires_graph=True),
        _q("b1", "Q3?", expected=["c"]),  # not requires_graph — doesn't count
    ]
    fake = FakeService(script={
        "Q1?": ("", "a yes"),       # graph win
        "Q2?": ("b yes", "b yes"),  # tie
        "Q3?": ("c yes", "c yes"),  # baseline; doesn't affect gate
    })
    summary = await run_eval(fake, tmp_path, questions=questions)
    assert summary.gate == "proceed"
    assert summary.requires_graph_graph_passing == 2
    assert summary.requires_graph_flat_passing == 1


@pytest.mark.asyncio
async def test_run_eval_publishes_failed_event_on_exception(
    event_capture, tmp_path, monkeypatch
) -> None:
    """If the inner compare blows up, the run aborts with a FAILED event
    (UI can show an error row instead of hanging)."""
    questions = [_q("x", "Q?", expected=["a"])]

    class BoomService:
        async def compare(self, *args, **kwargs):
            raise RuntimeError("provider blew up")

    with pytest.raises(RuntimeError, match="provider blew up"):
        await run_eval(BoomService(), tmp_path, questions=questions)

    types = [e.type for e in event_capture]
    assert KNOWLEDGE_EVAL_STARTED in types
    assert KNOWLEDGE_EVAL_FAILED in types
    failed = next(e for e in event_capture if e.type == KNOWLEDGE_EVAL_FAILED)
    assert "provider blew up" in failed.payload["error"]


@pytest.mark.asyncio
async def test_event_payload_workspace_path_matches_call_arg(
    event_capture, tmp_path
) -> None:
    """The SSE route filters events by workspace_path — verify every event
    carries the one we passed in (else the UI's subscription drops them)."""
    fake = FakeService(script={"Q?": ("ok", "ok")})
    await run_eval(fake, tmp_path, questions=[_q("x", "Q?", expected=["ok"])])
    for ev in event_capture:
        assert ev.workspace_path == tmp_path


def test_question_result_to_payload_shape() -> None:
    """Lock the payload shape — admin UI subscribes to these field names."""
    r = QuestionResult(
        id="x", category="c", question="q?", requires_graph=True,
        flat_mark=MARK_FAIL, flat_elapsed_ms=10, flat_answer="flat",
        flat_run_id="knowledge-flat-abc",
        graph_mark=MARK_PASS, graph_elapsed_ms=20, graph_answer="graph",
        graph_run_id="knowledge-graph-xyz",
        delta="+3",
    )
    p = r.to_payload(index=0, total=5)
    assert p["index"] == 0 and p["total"] == 5
    # 5e — per-leg run_id is part of the payload so the UI can render
    # "Open in Graph Runs" links per leg without an extra round-trip.
    assert set(p["flat"].keys()) == {"mark", "elapsed_ms", "answer_preview", "run_id"}
    assert set(p["graph"].keys()) == {"mark", "elapsed_ms", "answer_preview", "run_id"}
    assert p["flat"]["run_id"] == "knowledge-flat-abc"
    assert p["graph"]["run_id"] == "knowledge-graph-xyz"
    assert p["delta"] == "+3"


def test_question_result_to_payload_run_id_may_be_null() -> None:
    """When the underlying answer didn't record a run_id (e.g. no ledger
    configured), the payload exposes it as ``None`` rather than dropping the
    key — UI keeps its layout stable."""
    r = QuestionResult(
        id="x", category="c", question="q?", requires_graph=False,
        flat_mark=MARK_PASS, flat_elapsed_ms=5, flat_answer="a",
        flat_run_id=None,
        graph_mark=MARK_PASS, graph_elapsed_ms=5, graph_answer="a",
        graph_run_id=None,
        delta="0",
    )
    p = r.to_payload(index=0, total=1)
    assert p["flat"]["run_id"] is None
    assert p["graph"]["run_id"] is None


@pytest.mark.asyncio
async def test_question_result_answer_preview_is_truncated(
    event_capture, tmp_path
) -> None:
    """200-char preview — the SSE stream stays compact even when answers
    are long. Catches a future regression that ships full bodies."""
    long_answer = "a" * 500
    fake = FakeService(script={"Q?": (long_answer, long_answer)})
    await run_eval(fake, tmp_path, questions=[_q("x", "Q?", expected=["a"])])
    qc = next(e for e in event_capture if e.type == KNOWLEDGE_EVAL_QUESTION_COMPLETED)
    assert len(qc.payload["flat"]["answer_preview"]) <= 200
    assert len(qc.payload["graph"]["answer_preview"]) <= 200
