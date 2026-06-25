## Objective
Grade a model's Answer to a question about past conversations against the Ideal Answer, and
report the result as a single JSON object (see Output Fields). When a Rubric is shown, use it as
GUIDANCE on what a complete answer covers — not a checklist to fail on. Grade ONLY against the
Ideal Answer and Rubric — never your own knowledge.

## Verdicts
- pass: the Answer conveys the same fact(s) as the Ideal. Judge meaning, not wording —
  paraphrases, extra detail, and answers MORE specific than the Ideal all pass. When a Rubric is
  shown, an Answer that covers its MAIN elements passes — a missing minor element does NOT block
  a pass.
- partial: at least one correct item of a multi-part Ideal, or the right fact at lower precision
  than the Ideal. When a Rubric is shown, partial = the Answer captures some core elements but
  misses a substantial part of what was asked.
- fail: contradicts the Ideal or answers something else. When a Rubric is shown, fail = no element
  satisfied, the Answer misses the point, or it contradicts a rubric element.
- abstain: the Answer declines — "No information available." or any other refusal to answer.

## Core Instructions
- Rubric: when a Rubric section is shown, its lines describe what a complete answer would cover.
  Treat them as a GUIDE, not a pass/fail checklist — the Ideal Answer and the Rubric describe the
  same correct answer, so weigh whether the Answer captures the SUBSTANCE, not whether it states
  every line. Don't downgrade an otherwise-correct Answer for omitting a minor element.
- Dates: matching the Ideal's month and year passes; a correctly resolved relative date ("next
  month" stated in an August conversation = September) passes; within ~2 weeks passes.
- Negative Control = YES means declining is the correct outcome: an abstaining Answer is the
  right result, and a confident Answer is fail.
- The Recalled Memory Elements are what the answerer saw. They must NEVER change the verdict —
  use them only to fill evidence, recall_sufficient, and grounded.

## Output Fields
Reply with one JSON object containing exactly these fields, in this order:
- "evidence" (string): the exact line(s) copied VERBATIM from the Recalled Memory Elements that
  contain the information needed to answer; "" if no such line exists.
- "recall_sufficient" (boolean): true only if evidence quotes a real line that supplies the
  answer; false otherwise.
- "grounded" (boolean): whether the Answer is supported by the Recalled Memory Elements.
- "reason" (string): one short sentence justifying the verdict.
- "verdict" (string): one of "pass", "partial", "fail", "abstain".

## Validation
- evidence is checked by exact substring match against the shown elements — an inexact or
  invented quote counts as no evidence and forces recall_sufficient to false.
- If no Recalled Memory Elements section was shown, set evidence "" and recall_sufficient true.
- The verdict depends only on Answer vs Ideal (and Rubric, when shown).