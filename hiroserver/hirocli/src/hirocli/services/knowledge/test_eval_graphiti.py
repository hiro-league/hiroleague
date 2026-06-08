"""Tests for the Graphiti-pivot eval extensions.

Covers the extended question-bank fields (``expected_kind: abstain``, ``requires``)
and per-category aggregation. Pure — no service/DB.
"""

from __future__ import annotations

import pytest

from hirocli.services.knowledge.eval_runner import (
    LegResult,
    QuestionResult,
    category_breakdown,
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


def _qr(qid: str, cat: str, flat: str, graph: str) -> QuestionResult:
    # graph mark is the graphiti leg; these aggregation tests only exercise
    # per-category counting, not leg-specific behavior.
    return QuestionResult(
        id=qid,
        category=cat,
        question="q",
        requires_graph=True,
        legs={
            "flat": LegResult("flat", flat, 0, "", None),
            "graphiti": LegResult("graphiti", graph, 0, "", None),
        },
        delta="0",
    )


def test_category_breakdown() -> None:
    rows = [
        _qr("a", "direct", MARK_PASS, MARK_PASS),
        _qr("b", "multi_hop", MARK_FAIL, MARK_PASS),
        _qr("c", "multi_hop", MARK_FAIL, MARK_FAIL),
        _qr("d", "abstention", MARK_ABSTAIN, MARK_ABSTAIN),
    ]
    bd = category_breakdown(rows, ["flat", "graphiti"])
    assert bd["direct"] == {"total": 1, "pass": {"flat": 1, "graphiti": 1}}
    assert bd["multi_hop"] == {"total": 2, "pass": {"flat": 0, "graphiti": 1}}
    # abstain counts as a pass (correct outcome).
    assert bd["abstention"] == {"total": 1, "pass": {"flat": 1, "graphiti": 1}}
