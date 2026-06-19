"""Eval aggregation — per-mark breakdowns, per-field tables, the gate verdict.

Pure functions (no I/O) shared by both runners and the persisted-results read path:
``_summarize`` (knowledge ``EvalSummary`` + PROCEED/PIVOT gate) and ``summarize_memory_rows``
(memory dict summary). Reusable in tests without a workspace.
"""

from __future__ import annotations

import time
from typing import Any

from hirocli.services.eval.models import EvalSummary, QuestionResult
from hirocli.services.eval.scoring import (
    MARK_ABSTAIN,
    MARK_FAIL,
    MARK_PARTIAL,
    MARK_PASS,
    MARK_RANK,
    answer_score,
    is_correct,
)

# Answer-mark groups, in display order — the per-mark breakdown ("✓ ◐ ✗ 🛇") shown in the
# report tables. A row is CORRECT (see scoring.is_correct) when it's a pass, or an abstain
# on a negative-control row; correctness is NOT the same as the raw mark group (an abstain on a
# normal question is a miss, not a pass).
_MARK_GROUPS: tuple[tuple[str, str], ...] = (
    ("pass", MARK_PASS),
    ("partial", MARK_PARTIAL),
    ("fail", MARK_FAIL),
    ("abstain", MARK_ABSTAIN),
)

# Mark glyph → group name (pass/partial/fail/abstain) for the per-mark breakdown tally.
_MARK_TO_GROUP: dict[str, str] = {glyph: name for name, glyph in _MARK_GROUPS}


def _best_graph_delta_marks(marks: dict[str, str]) -> str:
    """Signed rank delta of the BEST graph leg's mark vs flat's — the table's Δ column.

    "+N" when a graph leg beats flat, "-N" when it trails, "0" on tie / when flat or all
    graph legs are absent / unjudged (empty marks rank 0, so an unjudged run shows Δ 0)."""
    flat = marks.get("flat")
    graph_marks = [mk for m, mk in marks.items() if m != "flat"]
    if flat is None or not graph_marks:
        return "0"
    best_graph = max(MARK_RANK.get(mk, 0) for mk in graph_marks)
    diff = best_graph - MARK_RANK.get(flat, 0)
    if diff > 0:
        return f"+{diff}"
    if diff < 0:
        return str(diff)
    return "0"


def _empty_breakdown_bucket(modes: list[str]) -> dict[str, Any]:
    """A fresh per-field bucket: total + per-leg group counts, correct count, graded score, and
    recall-sufficient count (judged rows the judge said had enough recalled context to answer)."""
    return {
        "total": 0,
        "groups": {m: {name: 0 for name, _ in _MARK_GROUPS} for m in modes},
        "correct": {m: 0 for m in modes},
        "score": {m: 0.0 for m in modes},
        "recall_ok": {m: 0 for m in modes},
        # Evidence recall (memory / LoCoMo): gold-evidence episodes the recall COVERED (matched)
        # of the total gold episodes, summed across this bucket's rows. NOT per-leg — it's a single
        # recall-leg concept — so two scalars, not a per-mode map. Stays 0/0 on the knowledge track
        # and on non-LoCoMo memory corpora (no evidence_recall on the rows).
        "evidence_matched": 0,
        "evidence_total": 0,
    }


def _tally_leg(
    bucket: dict[str, Any],
    mode: str,
    mark: str,
    *,
    is_negative_control: bool,
    recall_sufficient: bool = True,
) -> None:
    """Fold one leg's mark into a breakdown bucket: bump its group, correct count, score, and
    (for judged rows) the recall-sufficient count.

    Correct/score apply the negative-control rule (an abstain is correct only on a control row);
    the raw group tally just bins the mark as-is. Unjudged ("") marks count toward total only —
    and never toward recall_ok (recall_sufficient is only meaningful once the judge has run)."""
    group = _MARK_TO_GROUP.get(mark)
    if group is not None:
        bucket["groups"][mode][group] += 1
        if recall_sufficient:
            bucket["recall_ok"][mode] += 1
    if is_correct(mark, is_negative_control=is_negative_control):
        bucket["correct"][mode] += 1
    bucket["score"][mode] += answer_score(mark, is_negative_control=is_negative_control)


def field_breakdown(
    rows: list[QuestionResult],
    modes: list[str],
    *,
    field: str = "category",
    fallback: str = "uncategorized",
) -> dict[str, dict[str, Any]]:
    """Per-``field`` × N-leg breakdown — drives the per-category / per-difficulty report tables.

    Shape: ``{key: {"total", "groups": {leg: {pass,partial,fail,abstain}}, "correct": {leg},
    "score": {leg}}}``, keyed by the named ``QuestionResult`` attribute (``category`` or
    ``difficulty``). Pure so tests can reuse it. Empty attribute → ``fallback``."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = getattr(r, field, "") or fallback
        bucket = out.setdefault(key, _empty_breakdown_bucket(modes))
        bucket["total"] += 1
        neg = bool(getattr(r, "is_negative_control", False))
        for mode in modes:
            leg = r.legs.get(mode)
            if leg is not None:
                _tally_leg(
                    bucket, mode, leg.mark,
                    is_negative_control=neg,
                    recall_sufficient=bool(getattr(leg, "recall_sufficient", True)),
                )
    return out


def field_breakdown_rows(
    rows: list[dict[str, Any]],
    modes: list[str],
    *,
    field: str = "category",
    fallback: str = "uncategorized",
) -> dict[str, dict[str, Any]]:
    """Per-``field`` × leg breakdown over **dict** rows (the memory track's payloads).

    Mirrors :func:`field_breakdown` but reads ``row[field]``, ``row['is_negative_control']`` and
    ``row['legs'][mode]['mark']`` from the dict shape the memory runner emits. Empty → ``fallback``."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = str(r.get(field) or "") or fallback
        bucket = out.setdefault(key, _empty_breakdown_bucket(modes))
        bucket["total"] += 1
        neg = bool(r.get("is_negative_control"))
        legs = r.get("legs") or {}
        for mode in modes:
            leg = legs.get(mode) or {}
            _tally_leg(
                bucket, mode, str(leg.get("mark") or ""),
                is_negative_control=neg,
                recall_sufficient=bool(leg.get("recall_sufficient", True)),
            )
        # Evidence recall (LoCoMo): fold this row's X/Y gold-evidence coverage into the bucket so
        # the report can show a per-category / per-difficulty evidence total. Absent on non-LoCoMo
        # rows (left as 0/0). See EvidenceRecallContext / compute_evidence_recall_map.
        ev = r.get("evidence_recall")
        if isinstance(ev, dict):
            bucket["evidence_matched"] += int(ev.get("matched") or 0)
            bucket["evidence_total"] += int(ev.get("total") or 0)
    return out


def _memory_recall_leg(row: dict[str, Any]) -> dict[str, Any]:
    """The single ``recall`` leg of a memory-track question row (or ``{}``)."""
    return (row.get("legs") or {}).get("recall") or {}


def summarize_memory_rows(
    rows: list[dict[str, Any]],
    *,
    run_id: str = "merged",
    judged: bool | None = None,
) -> dict[str, Any]:
    """Aggregate a set of memory-track question rows into the summary payload.

    The single source of truth for the memory summary shape — used both by the
    live runner (one run's rows) and by the persisted-results read path (the
    merged per-corpus snapshot, where ``run_id``/ingest cost aren't meaningful).
    ``judged`` is inferred from the presence of judge marks when not given."""
    total = len(rows)
    if judged is None:
        # Merged read can't know the original judge flag → infer from the marks.
        judged = any(_memory_recall_leg(r).get("mark") for r in rows)
    # Overall correctness + per-mark groups + graded score for the single recall leg, applying the
    # negative-control rule (an abstain is correct only on a control row — the bug fix).
    overall = _empty_breakdown_bucket(["recall"])
    for r in rows:
        overall["total"] += 1
        leg = _memory_recall_leg(r)
        _tally_leg(
            overall, "recall", str(leg.get("mark") or ""),
            is_negative_control=bool(r.get("is_negative_control")),
            recall_sufficient=bool(leg.get("recall_sufficient", True)),
        )
    questions_cost_usd = sum(float(r.get("cost_usd") or 0.0) for r in rows)
    return {
        "run_id": run_id,
        "track": "memory",
        "total_questions": total,
        "modes": ["recall"],
        "judged": judged,
        "recalled_for": sum(1 for r in rows if _memory_recall_leg(r).get("recalled")),
        # Correct-count for the single recall leg (pass + correct-abstain; 0 when judge was off).
        "passing": {"recall": overall["correct"]["recall"]},
        # Per-mark distribution + graded score (partial = ½ pt) for the summary card.
        "groups": {"recall": overall["groups"]["recall"]},
        "scoring": {"recall": overall["score"]["recall"]},
        # No flat/graph legs → the PROCEED/PIVOT gate is undefined for the memory track.
        "gate": "n/a",
        "by_category": field_breakdown_rows(rows, ["recall"], field="category"),
        "by_difficulty": field_breakdown_rows(
            rows, ["recall"], field="difficulty", fallback="unspecified"
        ),
        # Sum of per-question recall elapsed — the merged snapshot has no single
        # wall-clock; the live runner overrides this with its real run duration.
        "elapsed_ms": sum(int(_memory_recall_leg(r).get("elapsed_ms") or 0) for r in rows),
        # Merged snapshot spans many runs → no single ingest cost; questions only.
        "ingest_cost_usd": 0.0,
        "questions_cost_usd": questions_cost_usd,
        "total_cost_usd": questions_cost_usd,
    }


def _summarize(
    run_id: str,
    rows: list[QuestionResult],
    started_at: float,
    modes: list[str],
    *,
    judged: bool = True,
) -> EvalSummary:
    """Compute the gate + per-leg aggregate counts the UI/CLI surfaces."""

    def _passing(subset: list[QuestionResult]) -> dict[str, int]:
        # A leg is CORRECT when pass, or abstain on a negative control (scoring.is_correct) —
        # the fix for counting every abstain as a pass.
        return {
            m: sum(
                1
                for r in subset
                if (leg := r.legs.get(m)) is not None
                and is_correct(leg.mark, is_negative_control=r.is_negative_control)
            )
            for m in modes
        }

    requires = [r for r in rows if r.requires_graph]
    passing = _passing(rows)
    req_passing = _passing(requires)
    # Overall per-mark groups + graded score across all legs (for the summary card).
    overall = _empty_breakdown_bucket(modes)
    for r in rows:
        for m in modes:
            leg = r.legs.get(m)
            if leg is not None:
                _tally_leg(
                    overall, m, leg.mark,
                    is_negative_control=r.is_negative_control,
                    recall_sufficient=leg.recall_sufficient,
                )
    # Gate: a graph leg must MEASURABLY beat flat on the requires_graph subset. Needs the
    # judge on (marks exist) AND flat + a graph leg; otherwise undefined → "n/a".
    graph_modes = [m for m in modes if m != "flat"]
    if judged and "flat" in modes and graph_modes:
        best_graph_req = max(req_passing[m] for m in graph_modes)
        gate = "proceed" if best_graph_req > req_passing["flat"] else "pivot"
    else:
        gate = "n/a"
    return EvalSummary(
        run_id=run_id,
        total_questions=len(rows),
        modes=list(modes),
        passing=passing,
        requires_graph_total=len(requires),
        requires_graph_passing=req_passing,
        gate=gate,
        judged=judged,
        elapsed_ms=int((time.perf_counter() - started_at) * 1000),
        questions=list(rows),
        by_category=field_breakdown(rows, modes, field="category"),
        by_difficulty=field_breakdown(rows, modes, field="difficulty", fallback="unspecified"),
        groups=overall["groups"],
        scoring=overall["score"],
        # LLM + reranker cost summed across questions (knowledge ingest cost deferred → 0).
        questions_cost_usd=sum(float(r.cost_usd or 0.0) for r in rows),
    )
