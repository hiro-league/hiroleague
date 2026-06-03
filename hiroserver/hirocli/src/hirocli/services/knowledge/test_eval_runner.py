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
    LegResult,
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
    run_id: str | None = None


class FakeService:
    """``answer_legs`` returns canned per-leg answers based on the question text
    so each scenario maps cleanly to a row in the scoring table.

    The script is ``query → (flat_answer, graph_answer)``; the graph answer is used
    for BOTH the "graphiti" and "mix" legs (the runner scores whatever legs the run
    selected). Per-leg elapsed differs so the payload's per-leg timings are testable."""

    _LEG_ELAPSED = {"flat": 10, "graphiti": 15, "mix": 20}

    def __init__(self, *, script: dict[str, tuple[str, str]]):
        # qid → (flat_answer, graph_answer)
        self._script = script
        self.legs_calls: list[dict[str, Any]] = []

    async def answer_legs(self, query, *, modes, top_k=None, min_score=None,
                          filters=None, workspace_id=None, explain=False,
                          rewrite=False, graph_temporal=None):
        self.legs_calls.append({
            "query": query, "modes": list(modes), "filters": filters,
            "rewrite": rewrite, "top_k": top_k, "min_score": min_score,
        })
        flat_ans, graph_ans = self._script.get(query, ("", ""))
        ans_for = {"flat": flat_ans, "graphiti": graph_ans, "mix": graph_ans}
        out: dict[str, FakeAnswerResult] = {}
        for mode in modes:
            text = ans_for.get(mode, "")
            out[mode] = FakeAnswerResult(
                answer=text,
                no_results=(text == ""),
                elapsed_ms=self._LEG_ELAPSED.get(mode, 5),
            )
        return out


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
    # Started payload — carries the selected legs so the UI renders columns up front.
    assert event_capture[0].payload["run_id"] == "rid-1"
    assert event_capture[0].payload["total_questions"] == 2
    assert event_capture[0].payload["modes"] == ["flat", "graphiti", "mix"]
    # Question events carry index/total + per-leg marks under ``legs``.
    qc1 = event_capture[1].payload
    assert qc1["index"] == 0 and qc1["total"] == 2 and qc1["id"] == "a"
    assert qc1["legs"]["flat"]["mark"] == MARK_FAIL
    assert qc1["legs"]["graphiti"]["mark"] == MARK_PASS
    assert qc1["legs"]["mix"]["mark"] == MARK_PASS
    assert qc1["delta"] == "+3"  # best graph leg vs flat
    # Summary payload matches what run_eval returned
    completed_payload = event_capture[-1].payload
    assert completed_payload["run_id"] == "rid-1"
    assert completed_payload["modes"] == ["flat", "graphiti", "mix"]
    # Q1 graph legs pass + Q2 all pass → graphiti/mix each pass 2, flat passes 1.
    assert completed_payload["passing"] == {"flat": 1, "graphiti": 2, "mix": 2}
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

    assert len(fake.legs_calls) == 1
    assert fake.legs_calls[0]["filters"]["tags"] == [EVAL_SYNTHETIC_TAG]


@pytest.mark.asyncio
async def test_run_eval_passes_through_caller_filters(event_capture, tmp_path) -> None:
    """Caller-supplied filters override the default tag scope (e.g. a tester
    wants to compare across the full workspace)."""
    fake = FakeService(script={"Q?": ("ok", "ok")})
    custom = {"tags": ["custom_tag"], "owner_kind": "system"}
    await run_eval(fake, tmp_path, questions=[_q("x", "Q?", expected=["ok"])], filters=custom)
    assert fake.legs_calls[0]["filters"] == custom


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
    assert summary.requires_graph_passing["mix"] == summary.requires_graph_passing["flat"]


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
    assert summary.requires_graph_passing["mix"] == 2
    assert summary.requires_graph_passing["graphiti"] == 2
    assert summary.requires_graph_passing["flat"] == 1


@pytest.mark.asyncio
async def test_run_eval_publishes_failed_event_on_exception(
    event_capture, tmp_path, monkeypatch
) -> None:
    """If the inner compare blows up, the run aborts with a FAILED event
    (UI can show an error row instead of hanging)."""
    questions = [_q("x", "Q?", expected=["a"])]

    class BoomService:
        async def answer_legs(self, *args, **kwargs):
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
        legs={
            "flat": LegResult("flat", MARK_FAIL, 10, "flat", "knowledge-flat-abc"),
            "graphiti": LegResult("graphiti", MARK_PARTIAL, 15, "gx", "knowledge-gx"),
            "mix": LegResult("mix", MARK_PASS, 20, "graph", "knowledge-graph-xyz"),
        },
        delta="+3",
    )
    p = r.to_payload(index=0, total=5)
    assert p["index"] == 0 and p["total"] == 5
    # legs is keyed by leg name; each leg carries the compact preview (terminal
    # line) AND the full answer (expandable row) + per-leg run_id for drill-in.
    assert set(p["legs"].keys()) == {"flat", "graphiti", "mix"}
    assert set(p["legs"]["flat"].keys()) == {
        "mode", "mark", "elapsed_ms", "answer_preview", "answer", "run_id"
    }
    assert p["legs"]["flat"]["answer"] == "flat"
    assert p["legs"]["mix"]["answer"] == "graph"
    assert p["legs"]["flat"]["run_id"] == "knowledge-flat-abc"
    assert p["legs"]["mix"]["run_id"] == "knowledge-graph-xyz"
    assert p["delta"] == "+3"


def test_question_result_to_payload_run_id_may_be_null() -> None:
    """When the underlying answer didn't record a run_id (e.g. no ledger
    configured), the payload exposes it as ``None`` rather than dropping the
    key — UI keeps its layout stable."""
    r = QuestionResult(
        id="x", category="c", question="q?", requires_graph=False,
        legs={
            "flat": LegResult("flat", MARK_PASS, 5, "a", None),
            "mix": LegResult("mix", MARK_PASS, 5, "a", None),
        },
        delta="0",
    )
    p = r.to_payload(index=0, total=1)
    assert p["legs"]["flat"]["run_id"] is None
    assert p["legs"]["mix"]["run_id"] is None


@pytest.mark.asyncio
async def test_run_eval_single_leg_runs_only_that_leg(event_capture, tmp_path) -> None:
    """A single-leg selection runs only that leg and gate is 'n/a' (no
    flat-vs-graph comparison possible)."""
    fake = FakeService(script={"Q?": ("flat ok", "graph ok")})
    summary = await run_eval(
        fake, tmp_path, questions=[_q("x", "Q?", expected=["ok"])], modes=["mix"]
    )
    assert summary.modes == ["mix"]
    assert fake.legs_calls[0]["modes"] == ["mix"]
    assert set(summary.passing.keys()) == {"mix"}
    assert summary.gate == "n/a"


@pytest.mark.asyncio
async def test_question_result_answer_preview_truncated_full_answer_intact(
    event_capture, tmp_path
) -> None:
    """The terminal-line ``answer_preview`` stays a compact 200-char teaser,
    while the full ``answer`` ships intact for the expandable table row."""
    long_answer = "a" * 500
    fake = FakeService(script={"Q?": (long_answer, long_answer)})
    await run_eval(fake, tmp_path, questions=[_q("x", "Q?", expected=["a"])])
    qc = next(e for e in event_capture if e.type == KNOWLEDGE_EVAL_QUESTION_COMPLETED)
    assert len(qc.payload["legs"]["flat"]["answer_preview"]) <= 200
    assert len(qc.payload["legs"]["mix"]["answer_preview"]) <= 200
    # Full answer is preserved (the panel reads the whole thing on row expand).
    assert qc.payload["legs"]["flat"]["answer"] == long_answer
    assert qc.payload["legs"]["mix"]["answer"] == long_answer
    # run_id rides on the question event too (registry correlation).
    assert qc.payload["run_id"]
