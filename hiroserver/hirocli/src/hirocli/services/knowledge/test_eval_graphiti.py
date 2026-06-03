"""Tests for the Graphiti-pivot eval extensions.

Covers ``must_not_contain`` scoring (superseded-fact leak), the extended
question-bank fields (``expected_kind: abstain``, ``must_not_contain``,
``requires``), and per-category aggregation. Pure — no service/DB.
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
    score_answer,
)


# ---- must_not_contain (superseded-fact / contradiction guard) ----


def test_must_not_contain_forces_fail() -> None:
    s = score_answer(
        "He drinks an oat-milk latte now, used to be espresso",
        ["oat", "latte"],
        no_results=False,
        must_not_contain=["espresso"],
    )
    assert s.mark == MARK_FAIL
    assert s.label == "forbidden_leak"


def test_must_not_contain_pass_when_clean() -> None:
    s = score_answer(
        "He drinks an oat-milk latte now",
        ["oat", "latte"],
        no_results=False,
        must_not_contain=["espresso"],
    )
    assert s.mark == MARK_PASS


def test_must_not_contain_does_not_upgrade_a_fail() -> None:
    s = score_answer(
        "nothing relevant", ["oat"], no_results=False, must_not_contain=["espresso"]
    )
    assert s.mark == MARK_FAIL
    assert s.label == "fail"  # plain fail, not forbidden_leak


def test_backward_compatible_without_must_not_contain() -> None:
    assert score_answer("an oat latte", ["oat", "latte"], no_results=False).mark == MARK_PASS


# ---- extended question-bank fields ----


def test_load_questions_abstain_kind(tmp_path) -> None:
    p = tmp_path / "q.yaml"
    p.write_text(
        '- id: q1\n  category: abstention\n  question: "blood type?"\n  expected_kind: abstain\n',
        encoding="utf-8",
    )
    qs = load_questions(p)
    assert qs[0]["expected_fragments"] == []  # negative control


def test_load_questions_must_not_contain_and_requires(tmp_path) -> None:
    p = tmp_path / "q.yaml"
    p.write_text(
        '- id: q1\n'
        '  category: knowledge_update\n'
        '  subcategory: conflict\n'
        '  question: "coffee now?"\n'
        '  expected_fragments: ["latte"]\n'
        '  must_not_contain: ["espresso"]\n'
        '  requires: [graph, temporal]\n',
        encoding="utf-8",
    )
    q = load_questions(p)[0]
    assert q["must_not_contain"] == ["espresso"]
    assert q["subcategory"] == "conflict"
    assert q["requires_graph"] is True  # derived from requires list


# ---- per-category aggregation ----


def _qr(qid: str, cat: str, flat: str, graph: str) -> QuestionResult:
    # graph mark is used for BOTH graph legs (graphiti + mix) in these aggregation
    # tests — they only exercise per-category counting, not the graphiti/mix split.
    return QuestionResult(
        id=qid,
        category=cat,
        question="q",
        requires_graph=True,
        legs={
            "flat": LegResult("flat", flat, 0, "", None),
            "graphiti": LegResult("graphiti", graph, 0, "", None),
            "mix": LegResult("mix", graph, 0, "", None),
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
    bd = category_breakdown(rows, ["flat", "graphiti", "mix"])
    assert bd["direct"] == {"total": 1, "pass": {"flat": 1, "graphiti": 1, "mix": 1}}
    assert bd["multi_hop"] == {"total": 2, "pass": {"flat": 0, "graphiti": 1, "mix": 1}}
    # abstain counts as a pass (correct outcome).
    assert bd["abstention"] == {"total": 1, "pass": {"flat": 1, "graphiti": 1, "mix": 1}}
