"""Unit tests for the L3 eval harness scoring + rendering logic.

The full harness needs a live workspace + LLM provider to run end-to-end —
that's the deliverable for manual / developer use. These tests cover the
*pure* logic (scoring, rendering, summary gate) so the table format doesn't
silently drift when the harness is edited.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_module():
    """Load the eval module from disk so this test file can sit next to it
    without making eval/ a Python package (it's a developer script, not a
    library).

    Must register the module in ``sys.modules`` **before** ``exec_module`` —
    decorators like ``@dataclass`` look up the declaring module by name via
    ``sys.modules[cls.__module__]``. Skipping this triggers an
    ``AttributeError: 'NoneType' has no attribute '__dict__'`` on class
    definition. (Standard importlib.util quirk.)
    """
    here = Path(__file__).parent
    name = "_l3_eval_under_test"
    spec = importlib.util.spec_from_file_location(name, here / "l3_synthetic_eval.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


eval_mod = _load_module()


# ---------------------------------------------------------------------------
# score_answer — the substring matcher + negative-control / abstain logic
# ---------------------------------------------------------------------------


def test_score_all_fragments_present_is_pass():
    s = eval_mod.score_answer(
        "Omar works at Acme as a senior engineer.",
        ["Omar", "Acme"],
        no_results=False,
    )
    assert s.mark == "✓"
    assert s.label == "pass"
    assert s.found == 2 and s.expected == 2


def test_score_some_fragments_is_partial():
    s = eval_mod.score_answer(
        "Omar is a great guy.", ["Omar", "Acme"], no_results=False
    )
    assert s.mark == "◐"
    assert s.found == 1 and s.expected == 2


def test_score_no_fragments_is_fail():
    s = eval_mod.score_answer(
        "I have no idea.", ["Omar", "Acme"], no_results=False
    )
    assert s.mark == "✗"
    assert s.found == 0 and s.expected == 2


def test_score_case_insensitive():
    s = eval_mod.score_answer(
        "OMAR works at acme.", ["Omar", "Acme"], no_results=False
    )
    assert s.mark == "✓"


def test_score_no_results_with_expected_is_fail():
    """The agent abstained but the question DID expect an answer → fail."""
    s = eval_mod.score_answer("", ["Omar"], no_results=True)
    assert s.mark == "✗"
    assert s.label == "no_results"


def test_score_no_results_with_no_expected_is_abstain():
    """Negative-control question: abstain is the correct outcome."""
    s = eval_mod.score_answer("", [], no_results=True)
    assert s.mark == "🛇"
    assert s.label == "abstain"


def test_score_confident_answer_with_no_expected_is_hallucination():
    """Negative control: producing a confident answer for a no-anchor
    question is the failure mode we want to catch."""
    s = eval_mod.score_answer(
        "The capital of France is Paris.", [], no_results=False
    )
    assert s.mark == "✗"
    assert s.label == "hallucinated"


def test_score_empty_answer_no_expected_is_abstain_even_without_no_results_flag():
    """An empty string is functionally an abstain regardless of the flag."""
    s = eval_mod.score_answer("", [], no_results=False)
    assert s.mark == "🛇"


# ---------------------------------------------------------------------------
# delta_mark — comparison logic
# ---------------------------------------------------------------------------


def _score(mark: str) -> "eval_mod.Score":
    return eval_mod.Score(mark=mark, label="x", found=0, expected=0)


def test_delta_graph_wins_on_pass_after_fail():
    assert eval_mod.delta_mark(_score("✗"), _score("✓")) == "+3"


def test_delta_graph_wins_partial_after_fail():
    assert eval_mod.delta_mark(_score("✗"), _score("◐")) == "+2"


def test_delta_tie_is_zero():
    assert eval_mod.delta_mark(_score("✓"), _score("✓")) == "0"
    assert eval_mod.delta_mark(_score("✗"), _score("✗")) == "0"


def test_delta_graph_loses_is_negative():
    assert eval_mod.delta_mark(_score("✓"), _score("✗")) == "-3"


def test_delta_abstain_ranks_above_fail():
    """Abstain is better than wrong: on a negative-control question, abstain
    is the correct outcome; on others, abstain at least avoids a bad answer."""
    assert eval_mod.delta_mark(_score("✗"), _score("🛇")) == "+1"


# ---------------------------------------------------------------------------
# render_table + render_summary — format-stability + gate computation
# ---------------------------------------------------------------------------


def _row(*, id_, requires_graph, off_mark, on_mark, q="q") -> "eval_mod.QuestionRow":
    return eval_mod.QuestionRow(
        id=id_,
        category="cat",
        question=q,
        requires_graph=requires_graph,
        off_score=_score(off_mark),
        off_elapsed_ms=0.0,
        off_answer="",
        on_score=_score(on_mark),
        on_elapsed_ms=0.0,
        on_answer="",
    )


def test_render_table_has_header_and_one_row_per_question():
    rows = [
        _row(id_="q1", requires_graph=True, off_mark="✗", on_mark="✓"),
        _row(id_="q2", requires_graph=False, off_mark="✓", on_mark="✓"),
    ]
    table = eval_mod.render_table(rows)
    lines = table.splitlines()
    # header + separator + 2 rows
    assert len(lines) == 4
    assert "id" in lines[0] and "flat" in lines[0] and "graph" in lines[0]
    assert "q1" in lines[2] and "✗" in lines[2] and "✓" in lines[2]
    # The requires_graph marker is in column 1 for q1, blank for q2.
    assert lines[2].startswith("▲")
    assert not lines[3].startswith("▲")


def test_summary_gate_proceed_when_graph_beats_flat_on_required_subset():
    rows = [
        _row(id_="r1", requires_graph=True, off_mark="✗", on_mark="✓"),
        _row(id_="r2", requires_graph=True, off_mark="✗", on_mark="✓"),
        _row(id_="r3", requires_graph=True, off_mark="✓", on_mark="✓"),
        _row(id_="b1", requires_graph=False, off_mark="✓", on_mark="✓"),
    ]
    summary = eval_mod.render_summary(rows)
    assert "PROCEED" in summary
    assert "graph passing: 3/3" in summary
    assert "flat passing:  1/3" in summary


def test_summary_gate_pivot_when_graph_does_not_beat_flat():
    rows = [
        _row(id_="r1", requires_graph=True, off_mark="✓", on_mark="✗"),
        _row(id_="r2", requires_graph=True, off_mark="✓", on_mark="✓"),
    ]
    summary = eval_mod.render_summary(rows)
    assert "PIVOT" in summary


def test_summary_gate_pivot_on_tie():
    """Strict gate: thesis must show measurable improvement, not parity."""
    rows = [
        _row(id_="r1", requires_graph=True, off_mark="✓", on_mark="✓"),
        _row(id_="r2", requires_graph=True, off_mark="✗", on_mark="✗"),
    ]
    summary = eval_mod.render_summary(rows)
    assert "PIVOT" in summary


def test_failures_detail_shows_only_rows_where_marks_differ():
    rows = [
        _row(id_="diff", requires_graph=True, off_mark="✗", on_mark="✓"),
        _row(id_="same", requires_graph=False, off_mark="✓", on_mark="✓"),
    ]
    out = eval_mod.render_failures_detail(rows)
    assert "diff" in out
    assert "same" not in out


# ---------------------------------------------------------------------------
# Synthetic corpus + questions YAML — sanity that they exist and parse
# ---------------------------------------------------------------------------


def test_synthetic_corpus_files_exist_and_are_nonempty():
    """Catch accidental deletion / encoding corruption of the corpus."""
    files = sorted(eval_mod.SYNTHETIC_CORPUS_DIR.glob("*.md"))
    assert len(files) >= 5, f"expected >=5 corpus files, got {len(files)}"
    for p in files:
        content = p.read_text(encoding="utf-8")
        assert len(content.strip()) >= 100, f"{p.name} is suspiciously short"


def test_questions_yaml_parses_with_required_fields():
    import yaml

    qs = yaml.safe_load(eval_mod.QUESTIONS_FILE.read_text(encoding="utf-8"))
    assert isinstance(qs, list) and len(qs) >= 8
    for q in qs:
        assert "id" in q and q["id"]
        assert "question" in q and q["question"].strip()
        assert "expected_fragments" in q  # may be empty list (negative control)
        assert isinstance(q["expected_fragments"], list)


def test_questions_include_at_least_one_negative_control():
    """The eval is only meaningful if it can also detect hallucinations on
    out-of-corpus questions. Lock in that there's at least one such row."""
    import yaml

    qs = yaml.safe_load(eval_mod.QUESTIONS_FILE.read_text(encoding="utf-8"))
    assert any(not q.get("expected_fragments") for q in qs)


def test_questions_include_arabic():
    """Multilingual coverage is part of the L3 thesis — keep it in the eval."""
    import yaml

    qs = yaml.safe_load(eval_mod.QUESTIONS_FILE.read_text(encoding="utf-8"))
    # Arabic alef is the cheap test — appears in our Arabic question.
    assert any(any("؀" <= ch <= "ۿ" for ch in q["question"]) for q in qs)
