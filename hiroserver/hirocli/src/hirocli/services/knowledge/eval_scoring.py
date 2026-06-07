"""Eval — pure scoring + delta math for the knowledge track, used by the in-process
runner (``services/knowledge/eval_runner.py``).

Kept dependency-free (no DB, no LangChain, no service imports) so the runner and the
pure-logic tests can import it without dragging service surface area along.
"""

from __future__ import annotations

from dataclasses import dataclass

# Marks: ✓ pass, ◐ partial, ✗ fail, 🛇 abstain (correct on negative-control rows).
MARK_PASS = "✓"
MARK_PARTIAL = "◐"
MARK_FAIL = "✗"
MARK_ABSTAIN = "🛇"

# Ranking is used by delta_mark and by the "graph beats flat" gate.
# Order: fail < abstain < partial < pass. Abstain is BETTER than wrong because
# on negative-control rows it's the correct outcome; on others it at least
# avoids a hallucinated answer.
MARK_RANK: dict[str, int] = {
    MARK_FAIL: 0,
    MARK_ABSTAIN: 1,
    MARK_PARTIAL: 2,
    MARK_PASS: 3,
}


@dataclass(frozen=True)
class Score:
    mark: str         # one of MARK_*
    label: str        # human-readable: "pass" / "partial" / "fail" / "abstain" / …
    found: int        # how many expected fragments matched
    expected: int     # how many fragments were expected (0 = negative control)


def _score_fragments(
    answer_text: str,
    expected_fragments: list[str],
    *,
    no_results: bool,
) -> Score:
    """Base substring scoring (no forbidden-fragment check)."""
    # Negative control — abstain wins.
    if not expected_fragments:
        if no_results or not (answer_text or "").strip():
            return Score(mark=MARK_ABSTAIN, label="abstain", found=0, expected=0)
        return Score(mark=MARK_FAIL, label="hallucinated", found=0, expected=0)

    if no_results:
        return Score(
            mark=MARK_FAIL,
            label="no_results",
            found=0,
            expected=len(expected_fragments),
        )

    text = (answer_text or "").lower()
    found = sum(1 for frag in expected_fragments if frag.lower() in text)
    total = len(expected_fragments)
    if found == total:
        return Score(mark=MARK_PASS, label="pass", found=found, expected=total)
    if found > 0:
        return Score(mark=MARK_PARTIAL, label="partial", found=found, expected=total)
    return Score(mark=MARK_FAIL, label="fail", found=found, expected=total)


def score_answer(
    answer_text: str,
    expected_fragments: list[str],
    *,
    no_results: bool,
    must_not_contain: list[str] | None = None,
) -> Score:
    """Score one answer against expected substring fragments.

    Substring match is case-insensitive and order-independent — a deliberate
    lower bound on quality, so a passing row means the bare strings appeared
    but doesn't guarantee the answer was coherent.

    Empty ``expected_fragments`` is the **negative control**: abstain (no_results
    or empty answer) is the correct outcome; a confident answer is a fail
    (likely hallucination).

    ``must_not_contain`` is the **superseded-fact / contradiction guard**: if the
    answer contains any forbidden fragment (e.g. the old city after a move, the
    old job after a switch), the row is forced to ``fail`` even if the expected
    fragments were present. Catches the temporal-leak failure mode the Graphiti
    pivot is meant to fix (docs/knowledge-graphiti-pivot-design.md §8.6).
    """
    base = _score_fragments(answer_text, expected_fragments, no_results=no_results)

    forbidden = [f for f in (must_not_contain or []) if f]
    if forbidden and base.mark != MARK_FAIL and (answer_text or "").strip():
        text = (answer_text or "").lower()
        if any(f.lower() in text for f in forbidden):
            return Score(
                mark=MARK_FAIL,
                label="forbidden_leak",
                found=base.found,
                expected=base.expected,
            )
    return base


def delta_mark(off: Score, on: Score) -> str:
    """Signed delta between two scores' ranks. ``"+N"`` if graph won, ``"-N"``
    if graph lost, ``"0"`` on tie. Used for the side-by-side table column."""
    off_rank = MARK_RANK.get(off.mark, 0)
    on_rank = MARK_RANK.get(on.mark, 0)
    if on_rank > off_rank:
        return f"+{on_rank - off_rank}"
    if on_rank < off_rank:
        return f"{on_rank - off_rank}"
    return "0"


__all__ = [
    "MARK_ABSTAIN",
    "MARK_FAIL",
    "MARK_PARTIAL",
    "MARK_PASS",
    "MARK_RANK",
    "Score",
    "delta_mark",
    "score_answer",
]
