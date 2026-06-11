"""Tests for the Graphiti-pivot eval extensions.

Covers the extended question-bank fields (``expected_kind: abstain``, ``requires``)
and per-category aggregation. Pure — no service/DB.
"""

from __future__ import annotations

import pytest

from hirocli.services.knowledge.eval_runner import (
    LegResult,
    QuestionResult,
    field_breakdown,
    field_breakdown_rows,
    load_questions,
)
from hirocli.services.knowledge.eval_scoring import (
    MARK_ABSTAIN,
    MARK_FAIL,
    MARK_PARTIAL,
    MARK_PASS,
)


# ---- extended question-bank fields ----


def test_load_questions_abstain_kind(tmp_path) -> None:
    p = tmp_path / "q.yaml"
    p.write_text(
        '- id: q1\n  category: abstention\n  question: "blood type?"\n  expected_kind: abstain\n',
        encoding="utf-8",
    )
    qs = load_questions(p)
    assert qs[0]["expected_fragments"] == []  # negative control


def test_load_questions_difficulty_passthrough(tmp_path) -> None:
    p = tmp_path / "q.yaml"
    p.write_text(
        '- id: q1\n'
        '  category: multi_hop\n'
        '  difficulty: Very_Hard\n'  # normalized to lowercase
        '  question: "who?"\n'
        '  expected_answer: "x"\n'
        '- id: q2\n'
        '  category: direct_recall\n'  # difficulty omitted → ""
        '  question: "what?"\n'
        '  expected_answer: "y"\n',
        encoding="utf-8",
    )
    qs = load_questions(p)
    assert qs[0]["difficulty"] == "very_hard"
    assert qs[1]["difficulty"] == ""  # optional — missing is fine


def test_load_questions_requires(tmp_path) -> None:
    p = tmp_path / "q.yaml"
    p.write_text(
        '- id: q1\n'
        '  category: knowledge_update\n'
        '  subcategory: conflict\n'
        '  question: "coffee now?"\n'
        '  expected_fragments: ["latte"]\n'
        '  requires: [graph, temporal]\n',
        encoding="utf-8",
    )
    q = load_questions(p)[0]
    assert q["subcategory"] == "conflict"
    assert q["requires_graph"] is True  # derived from requires list


# ---- per-category aggregation ----


def _qr(
    qid: str,
    cat: str,
    flat: str,
    graph: str,
    difficulty: str = "",
    *,
    is_negative_control: bool = False,
) -> QuestionResult:
    # graph mark is the graphiti leg; these aggregation tests only exercise
    # per-field counting, not leg-specific behavior.
    return QuestionResult(
        id=qid,
        category=cat,
        difficulty=difficulty,
        question="q",
        requires_graph=True,
        legs={
            "flat": LegResult("flat", flat, 0, "", None),
            "graphiti": LegResult("graphiti", graph, 0, "", None),
        },
        delta="0",
        is_negative_control=is_negative_control,
    )


def test_field_breakdown_by_category() -> None:
    rows = [
        _qr("a", "direct", MARK_PASS, MARK_PASS),
        _qr("b", "multi_hop", MARK_FAIL, MARK_PASS),
        _qr("c", "multi_hop", MARK_FAIL, MARK_FAIL),
        # Negative control: an abstain here IS correct.
        _qr("d", "abstention", MARK_ABSTAIN, MARK_ABSTAIN, is_negative_control=True),
    ]
    bd = field_breakdown(rows, ["flat", "graphiti"], field="category")
    assert bd["direct"]["total"] == 1
    assert bd["direct"]["correct"] == {"flat": 1, "graphiti": 1}
    assert bd["multi_hop"]["total"] == 2
    assert bd["multi_hop"]["correct"] == {"flat": 0, "graphiti": 1}
    assert bd["multi_hop"]["groups"]["flat"] == {"pass": 0, "partial": 0, "fail": 2, "abstain": 0}
    # abstain on a negative control counts as correct.
    assert bd["abstention"]["correct"] == {"flat": 1, "graphiti": 1}
    assert bd["abstention"]["groups"]["flat"]["abstain"] == 1


def test_field_breakdown_abstain_only_correct_on_control() -> None:
    # Same mark (abstain) on a NORMAL question is NOT correct — the bug fix.
    rows = [
        _qr("normal", "recall", MARK_ABSTAIN, MARK_ABSTAIN, is_negative_control=False),
        _qr("control", "abstention", MARK_ABSTAIN, MARK_ABSTAIN, is_negative_control=True),
    ]
    bd = field_breakdown(rows, ["flat", "graphiti"], field="category")
    assert bd["recall"]["correct"] == {"flat": 0, "graphiti": 0}
    assert bd["abstention"]["correct"] == {"flat": 1, "graphiti": 1}
    # Both still tally under the raw 'abstain' group regardless of correctness.
    assert bd["recall"]["groups"]["flat"]["abstain"] == 1


def test_field_breakdown_partial_scores_half() -> None:
    rows = [_qr("a", "recall", MARK_PARTIAL, MARK_PASS)]
    bd = field_breakdown(rows, ["flat", "graphiti"], field="category")
    # Partial is not "correct" but scores half a point.
    assert bd["recall"]["correct"] == {"flat": 0, "graphiti": 1}
    assert bd["recall"]["score"] == {"flat": 0.5, "graphiti": 1.0}
    assert bd["recall"]["groups"]["flat"]["partial"] == 1


def test_field_breakdown_by_difficulty() -> None:
    rows = [
        _qr("a", "direct", MARK_PASS, MARK_PASS, difficulty="medium"),
        _qr("b", "multi_hop", MARK_FAIL, MARK_PASS, difficulty="hard"),
        _qr("c", "multi_hop", MARK_FAIL, MARK_FAIL, difficulty="hard"),
        _qr("d", "abstention", MARK_PASS, MARK_PASS),  # no difficulty → fallback bucket
    ]
    bd = field_breakdown(rows, ["flat", "graphiti"], field="difficulty", fallback="unspecified")
    assert bd["medium"]["correct"] == {"flat": 1, "graphiti": 1}
    assert bd["hard"]["total"] == 2
    assert bd["hard"]["correct"] == {"flat": 0, "graphiti": 1}
    assert bd["unspecified"]["correct"] == {"flat": 1, "graphiti": 1}


def test_field_breakdown_rows_by_difficulty() -> None:
    # Dict-row variant (the memory track's payload shape), single recall leg.
    rows = [
        {"difficulty": "medium", "legs": {"recall": {"mark": MARK_PASS}}},
        {"difficulty": "very_hard", "legs": {"recall": {"mark": MARK_FAIL}}},
        # Negative-control abstain → correct; missing difficulty → fallback bucket.
        {"is_negative_control": True, "legs": {"recall": {"mark": MARK_ABSTAIN}}},
    ]
    bd = field_breakdown_rows(rows, ["recall"], field="difficulty", fallback="unspecified")
    assert bd["medium"]["correct"] == {"recall": 1}
    assert bd["very_hard"]["correct"] == {"recall": 0}
    # abstain on a negative control counts as correct on the recall leg.
    assert bd["unspecified"]["correct"] == {"recall": 1}


def test_field_breakdown_rows_recall_sufficiency() -> None:
    # recall_ok counts judged rows the judge flagged recall_sufficient; unjudged ("") rows never
    # count, even though recall_sufficient defaults true.
    rows = [
        {"category": "recall", "legs": {"recall": {"mark": MARK_PASS, "recall_sufficient": True}}},
        {"category": "recall", "legs": {"recall": {"mark": MARK_FAIL, "recall_sufficient": False}}},
        {"category": "recall", "legs": {"recall": {"mark": "", "recall_sufficient": True}}},  # unjudged
    ]
    bd = field_breakdown_rows(rows, ["recall"], field="category")
    assert bd["recall"]["recall_ok"] == {"recall": 1}  # only the judged + sufficient row


def test_field_breakdown_rows_abstain_not_correct_without_control() -> None:
    # Dict-row abstain WITHOUT the negative-control flag is a miss, not a pass (the bug fix).
    rows = [{"category": "recall", "legs": {"recall": {"mark": MARK_ABSTAIN}}}]
    bd = field_breakdown_rows(rows, ["recall"], field="category")
    assert bd["recall"]["correct"] == {"recall": 0}
    assert bd["recall"]["groups"]["recall"]["abstain"] == 1
