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
    """Base substring scoring."""
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
) -> Score:
    """Score one answer against expected substring fragments.

    Substring match is case-insensitive and order-independent — a deliberate
    lower bound on quality, so a passing row means the bare strings appeared
    but doesn't guarantee the answer was coherent.

    Empty ``expected_fragments`` is the **negative control**: abstain (no_results
    or empty answer) is the correct outcome; a confident answer is a fail
    (likely hallucination).
    """
    return _score_fragments(answer_text, expected_fragments, no_results=no_results)


def is_correct(mark: str, *, is_negative_control: bool) -> bool:
    """Whether a judge mark counts as CORRECT for aggregate scoring.

    A pass is always correct. An abstain (🛇) is correct ONLY on a negative-control row
    (where declining is the right outcome) — on a normal question an abstain is a
    recall/answering miss, NOT a pass. This is the fix for the old bug where any abstain
    was counted as correct regardless of whether the question was a negative control.
    Partial and fail are never "correct" (partial scores half via :func:`answer_score`)."""
    if mark == MARK_PASS:
        return True
    if mark == MARK_ABSTAIN:
        return is_negative_control
    return False


def answer_score(mark: str, *, is_negative_control: bool) -> float:
    """Graded score for one mark: 1.0 if correct (see :func:`is_correct`), 0.5 for a
    partial, 0.0 otherwise. Drives the "Score %" metric (partial = half point)."""
    if is_correct(mark, is_negative_control=is_negative_control):
        return 1.0
    if mark == MARK_PARTIAL:
        return 0.5
    return 0.0


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
    "answer_score",
    "delta_mark",
    "is_correct",
    "score_answer",
]
