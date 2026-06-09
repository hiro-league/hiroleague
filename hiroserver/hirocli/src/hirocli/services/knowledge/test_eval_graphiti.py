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


def _qr(qid: str, cat: str, flat: str, graph: str, difficulty: str = "") -> QuestionResult:
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
    )


def test_field_breakdown_by_category() -> None:
    rows = [
        _qr("a", "direct", MARK_PASS, MARK_PASS),
        _qr("b", "multi_hop", MARK_FAIL, MARK_PASS),
        _qr("c", "multi_hop", MARK_FAIL, MARK_FAIL),
        _qr("d", "abstention", MARK_ABSTAIN, MARK_ABSTAIN),
    ]
    bd = field_breakdown(rows, ["flat", "graphiti"], field="category")
    assert bd["direct"] == {"total": 1, "pass": {"flat": 1, "graphiti": 1}}
    assert bd["multi_hop"] == {"total": 2, "pass": {"flat": 0, "graphiti": 1}}
    # abstain counts as a pass (correct outcome).
    assert bd["abstention"] == {"total": 1, "pass": {"flat": 1, "graphiti": 1}}


def test_field_breakdown_by_difficulty() -> None:
    rows = [
        _qr("a", "direct", MARK_PASS, MARK_PASS, difficulty="medium"),
        _qr("b", "multi_hop", MARK_FAIL, MARK_PASS, difficulty="hard"),
        _qr("c", "multi_hop", MARK_FAIL, MARK_FAIL, difficulty="hard"),
        _qr("d", "abstention", MARK_PASS, MARK_PASS),  # no difficulty → fallback bucket
    ]
    bd = field_breakdown(rows, ["flat", "graphiti"], field="difficulty", fallback="unspecified")
    assert bd["medium"] == {"total": 1, "pass": {"flat": 1, "graphiti": 1}}
    assert bd["hard"] == {"total": 2, "pass": {"flat": 0, "graphiti": 1}}
    assert bd["unspecified"] == {"total": 1, "pass": {"flat": 1, "graphiti": 1}}


def test_field_breakdown_rows_by_difficulty() -> None:
    # Dict-row variant (the memory track's payload shape), single recall leg.
    rows = [
        {"difficulty": "medium", "legs": {"recall": {"mark": MARK_PASS}}},
        {"difficulty": "very_hard", "legs": {"recall": {"mark": MARK_FAIL}}},
        {"legs": {"recall": {"mark": MARK_ABSTAIN}}},  # missing → fallback
    ]
    bd = field_breakdown_rows(rows, ["recall"], field="difficulty", fallback="unspecified")
    assert bd["medium"] == {"total": 1, "pass": {"recall": 1}}
    assert bd["very_hard"] == {"total": 1, "pass": {"recall": 0}}
    # abstain counts as a pass on the recall leg.
    assert bd["unspecified"] == {"total": 1, "pass": {"recall": 1}}
