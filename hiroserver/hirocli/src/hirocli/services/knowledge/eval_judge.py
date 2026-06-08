"""Eval LLM steps — answer-from-context + an optional LLM judge, shared by both tracks.

Replaces the old substring scorer (dropped): instead of matching fragments, an LLM **judge**
grades the model's answer against the ideal answer (``expected_answer``) and the superseded-value
guard (``must_not_contain``), returning a mark compatible with the existing ``Score``/``MARK_*``
(so the table marks, Δ, gate, and per-category breakdown keep working).

Two steps, both reusing the workspace **answering model** and both ledgered as their own node
(``eval_answer`` / ``eval_judge``) under the caller's active run, so they show as priced sub-rows
in Graph Runs:

* :func:`answer_from_context` — a brief answer grounded ONLY in the supplied context (the recalled
  facts for memory). Grounding is the eval's integrity: the model must not use outside knowledge,
  and must decline when the context doesn't cover the question.
* :func:`judge_answer` — verdict (pass / partial / fail / abstain) + reason, vs the ideal answer.

The judge is optional (Phase: the caller passes ``judge=False`` to skip scoring and only collect
answers). Both functions no-op the ledger when ``sink is None`` (tests / CLI).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hiro_commons.log import Logger
from pydantic import BaseModel, Field

from hirocli.services.knowledge.eval_scoring import (
    MARK_ABSTAIN,
    MARK_FAIL,
    MARK_PARTIAL,
    MARK_PASS,
)

log = Logger.get("SVC.KNOWLEDGE.EVAL.JUDGE")

# verdict word (from the judge) → mark glyph (the shared scoring alphabet).
_VERDICT_TO_MARK = {
    "pass": MARK_PASS,
    "partial": MARK_PARTIAL,
    "fail": MARK_FAIL,
    "abstain": MARK_ABSTAIN,
}


@dataclass(frozen=True)
class JudgeVerdict:
    """One judge outcome: a mark glyph + short reason (and whether the answer was grounded)."""

    mark: str
    reason: str
    grounded: bool = True


class _JudgeOutput(BaseModel):
    """Structured judge response (LLM-filled)."""

    verdict: str = Field(description="one of: pass, partial, fail, abstain")
    grounded: bool = Field(description="true if the answer is supported by the provided context")
    reason: str = Field(description="one short sentence justifying the verdict")


def _provider_model(model_id: str) -> tuple[str, str]:
    """Split a ``provider:model`` id for ledger attribution; tolerate a bare id."""
    if ":" in model_id:
        provider, _, model = model_id.partition(":")
        return provider, model
    return "", model_id


async def _ledger_llm_node(
    sink: Any | None,
    node: str,
    model_id: str,
    *,
    input_preview: str,
    call: Any,
) -> Any:
    """Run one model call as a ledgered node under the active run, recording token usage.

    ``call`` is a 0-arg async callable returning ``(result, ai_message, output_preview)`` where
    ``ai_message`` carries ``usage_metadata`` (may be ``None``). Returns ``result``. With
    ``sink is None`` the call runs unledgered (tests / CLI)."""
    if sink is None:
        result, _ai, _preview = await call()
        return result

    from hirocli.runtime.agent_graph.ledger import current_entry

    provider, model = _provider_model(model_id)
    entry = sink.open_entry(node, {}, None)  # run id resolves from the active current_run
    token = current_entry.set(entry)
    status, error_code = "ok", ""
    try:
        result, ai, output_preview = await call()
        usage = getattr(ai, "usage_metadata", None) or {}
        entry.add_usage(
            provider=provider,
            model=model,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
        )
        entry.input_preview = input_preview
        entry.output_preview = output_preview
        return result
    except Exception as exc:
        status, error_code = "error", type(exc).__name__
        raise
    finally:
        entry.finish("ok" if status == "ok" else "error", error_code=error_code)
        sink.write_rows(entry.rows(include_parent=True))
        current_entry.reset(token)


_ANSWER_SYSTEM = (
    "You answer a question using ONLY the facts provided. Do not use any outside or prior "
    "knowledge. If the facts do not contain the answer, reply exactly: I don't know. "
    "Answer in one short sentence."
)


async def answer_from_context(
    model: Any,
    model_id: str,
    *,
    question: str,
    context: list[str],
    sink: Any | None = None,
) -> str:
    """Brief answer to ``question`` grounded ONLY in ``context`` (the recalled facts).

    Ledgered as an ``eval_answer`` node. Empty context ⇒ the model is asked over no facts, so it
    should decline (tests memory recall honestly)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from hirocli.runtime.agent_graph.base import _normalize_reply_content

    facts = "\n".join(f"- {c}" for c in context) or "(no facts available)"
    human = f"Facts:\n{facts}\n\nQuestion: {question}"

    async def _call() -> tuple[str, Any, str]:
        ai = await model.ainvoke([SystemMessage(_ANSWER_SYSTEM), HumanMessage(human)])
        # Flatten provider content (Anthropic returns a list of text blocks) to plain text;
        # str() on the raw list leaked a JSON-ish repr into the recall answer. Reuse the
        # shared agent-graph normalizer instead of duplicating block-extraction here.
        text = _normalize_reply_content(getattr(ai, "content", "")).strip()
        return text, ai, text[:200]

    return await _ledger_llm_node(
        sink, "eval_answer", model_id, input_preview=f"q: {question[:160]}", call=_call
    )


_JUDGE_SYSTEM = (
    "You are a strict grader. Compare a model's ANSWER to the IDEAL answer for a question and "
    "return a verdict:\n"
    "- pass: the answer matches the ideal (same facts).\n"
    "- partial: partially correct or incomplete.\n"
    "- fail: wrong, or it states any of the FORBIDDEN (superseded) values.\n"
    "- abstain: the answer declines / says it doesn't know.\n"
    "If the question is a NEGATIVE CONTROL (declining is correct), then 'abstain' is the right "
    "outcome and a confident answer is 'fail'. Judge only against the IDEAL — never your own "
    "knowledge."
)


async def judge_answer(
    model: Any,
    model_id: str,
    *,
    question: str,
    answer: str,
    expected_answer: str,
    must_not_contain: list[str],
    is_negative_control: bool = False,
    sink: Any | None = None,
) -> JudgeVerdict:
    """Grade ``answer`` against the ideal ``expected_answer`` → :class:`JudgeVerdict`.

    Ledgered as an ``eval_judge`` node. Falls back to a ``fail`` verdict (not an exception) if the
    judge call errors, so one bad grade never aborts the run."""
    from langchain_core.messages import HumanMessage, SystemMessage

    forbidden = ", ".join(f for f in must_not_contain if f) or "(none)"
    control = "YES — declining is the correct outcome." if is_negative_control else "no"
    human = (
        f"Question: {question}\n"
        f"IDEAL answer: {expected_answer or '(none given)'}\n"
        f"FORBIDDEN (superseded) values: {forbidden}\n"
        f"Negative control: {control}\n\n"
        f"Model ANSWER: {answer or '(empty)'}"
    )
    structured = model.with_structured_output(_JudgeOutput, include_raw=True)

    async def _call() -> tuple[JudgeVerdict, Any, str]:
        raw = await structured.ainvoke([SystemMessage(_JUDGE_SYSTEM), HumanMessage(human)])
        parsed: _JudgeOutput | None = raw.get("parsed") if isinstance(raw, dict) else raw
        ai = raw.get("raw") if isinstance(raw, dict) else None
        verdict_word = str(getattr(parsed, "verdict", "") or "").strip().lower()
        mark = _VERDICT_TO_MARK.get(verdict_word, MARK_FAIL)
        reason = str(getattr(parsed, "reason", "") or "").strip()
        grounded = bool(getattr(parsed, "grounded", True))
        return JudgeVerdict(mark=mark, reason=reason, grounded=grounded), ai, f"{mark} {reason[:120]}"

    try:
        return await _ledger_llm_node(
            sink, "eval_judge", model_id, input_preview=f"q: {question[:120]}", call=_call
        )
    except Exception:
        log.warning("⚠️ knowledge.eval — judge call failed · q=%s", question[:80], exc_info=True)
        return JudgeVerdict(mark=MARK_FAIL, reason="judge error", grounded=False)


__all__ = ["JudgeVerdict", "answer_from_context", "judge_answer"]
