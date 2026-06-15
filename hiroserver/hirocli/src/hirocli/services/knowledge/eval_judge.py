"""Eval LLM steps — answer-from-context + an optional LLM judge, shared by both tracks.

Replaces the old substring scorer (dropped): instead of matching fragments, an LLM **judge**
grades the model's answer against the ideal answer (``expected_answer``), returning a mark
compatible with the existing ``Score``/``MARK_*`` (so the table marks, Δ, gate, and per-category
breakdown keep working).

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

from hirocli.domain.preferences import (
    DEFAULT_MEMORY_EVAL_ANSWER_PROMPT,
    DEFAULT_MEMORY_EVAL_JUDGE_PROMPT,
)

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
    """One judge outcome: a mark glyph + short reason (and whether the answer was grounded).

    ``recall_sufficient`` lets the eval attribute a miss: ``False`` ⇒ the recalled context did NOT
    contain the info needed to answer (a *recall* failure), vs a *answering* failure when the
    context was sufficient but the answer was still wrong. Defaults ``True`` (judge unaware / not
    asked, e.g. the knowledge track which passes no context)."""

    mark: str
    reason: str
    grounded: bool = True
    recall_sufficient: bool = True
    # The context line(s) the judge quoted as supporting the answer — surfaced in the eval UI's
    # Judge section. Only set when the quote was verified present in the context (else ""), so a
    # displayed quote is always a real recalled line, never a judge hallucination.
    # (Was declared twice by mistake; collapsed to one field.)
    evidence: str = ""


@dataclass(frozen=True)
class RecallRenderOptions:
    """Which per-fact temporal annotations the recalled-context renderer emits.

    Mirrors the ``graph.eval.show_*`` prefs. Each fact's ``event_time`` (valid_at), ``expired_at``
    (invalid_at), and ``SUPERSEDED`` flag is independently shown/hidden; ``show_event_time`` ALSO
    governs the episode ``[date]`` prefix (decision: one date toggle covers both kinds). Field
    names match the labels the answerer prompt references (Zep-style ``event_time``/``expired_at``,
    not the old ``valid → invalid`` range). Defaults = the pref defaults: event_time on, expired_at
    and superseded off (a single timestamp per fact)."""

    show_event_time: bool = True
    show_expired_at: bool = False
    show_superseded: bool = False


class _JudgeOutput(BaseModel):
    """Structured judge response (LLM-filled).

    Field order is deliberate: structured output is generated top-to-bottom, so the judge quotes
    its evidence and writes its reason BEFORE committing the verdict — a built-in look-before-you-
    grade step that lets a FLAT (non-reasoning) judge model gather grounds first."""

    evidence: str = Field(
        default="",
        description=(
            "the exact line(s) copied verbatim from the RECALLED CONTEXT that supply the answer; "
            "empty if the context contains no such line. Required to justify recall_sufficient=true."
        ),
    )
    recall_sufficient: bool = Field(
        default=True,
        description=(
            "true ONLY if `evidence` quotes a real line from the recalled context that supplies the "
            "answer; false when the needed fact was not recalled (a recall miss, not an answering "
            "miss). If no context was provided, leave true."
        ),
    )
    grounded: bool = Field(
        default=True, description="true if the answer is supported by the provided context"
    )
    reason: str = Field(description="one short sentence justifying the verdict")
    verdict: str = Field(description="one of: pass, partial, fail, abstain")


# Hardcoded answering role (NOT a preference): the editable graph.eval.memory_answer_prompt is the
# INSTRUCTION block placed in the user message, so the system prompt stays a stable two-line role.
MEMORY_EVAL_ANSWER_SYSTEM_PROMPT = (
    "You are a professional memory analyst. You answer user questions strictly from recalled "
    "conversation-memory elements provided to you, with precise attribution of who did what and "
    "exact resolution of dates."
)

# Per-kind section order + heading for the recalled-context prompt (facts → entities → messages).
# Markdown "###" headings match the "## Recalled Memory Elements" layout the answer instructions
# define; episodes surface as "Relevant Messages" (the instructions' name for raw turns).
_RECALL_SECTIONS: tuple[tuple[str, str], ...] = (
    ("fact", "### Relevant Facts"),
    ("entity", "### Relevant Entities"),
    ("episode", "### Relevant Messages"),
)


def _format_recall_item(hit: dict[str, Any], render: RecallRenderOptions) -> str:
    """One recalled item → a prompt line WITH useful metadata, but NOT the retrieval score.

    Score is a ranking artifact that doesn't help the model answer (and can bias it), so it stays
    in the ledger/UI only. Metadata kept: relationship + temporal validity (facts), type (entities),
    timestamp (episodes). ``render`` toggles which temporal annotations appear (graph.eval.show_*)."""
    kind = str(hit.get("kind") or "fact")
    if kind == "entity":
        name = str(hit.get("name") or "").strip()
        etype = str(hit.get("entity_type") or "").strip()
        summary = str(hit.get("summary") or hit.get("memory") or "").strip()
        head = f"{name} ({etype})" if name and etype else (name or "entity")
        return f"{head}: {summary}" if summary else head
    if kind == "episode":
        when = str(hit.get("valid_at") or "").strip()
        body = str(hit.get("memory") or "").strip()
        # The episode [date] prefix is governed by the same show_event_time toggle as a fact's
        # event_time (decision: one date toggle for both kinds).
        return f"[{when}] {body}" if (when and render.show_event_time) else body
    # fact (default): raw fact + relationship + temporal validity/supersession.
    fact = str(hit.get("fact") or hit.get("memory") or "").strip()
    rel = str(hit.get("name") or "").strip()
    valid_at = str(hit.get("valid_at") or "").strip()
    invalid_at = str(hit.get("invalid_at") or "").strip()
    bits: list[str] = []
    if rel:
        bits.append(rel)
    # Temporal annotations are independently toggleable (graph.eval.show_*), and renamed from the
    # old "valid X → Y" range to event_time/expired_at so the labels match the answerer prompt.
    if render.show_event_time and valid_at:
        bits.append(f"event_time: {valid_at}")
    if render.show_expired_at and invalid_at:
        bits.append(f"expired_at: {invalid_at}")
    if render.show_superseded and hit.get("superseded"):
        bits.append("SUPERSEDED")
    return f"{fact} [{' · '.join(bits)}]" if bits else fact


def format_recall_context(
    hits: "list[dict[str, Any]] | None", render: RecallRenderOptions | None = None
) -> str:
    """Render recalled hits into markdown sections (Relevant Facts / Entities / Messages) — only
    the kinds that exist, each item with metadata (no score). Shared by the answer + judge prompts
    so both see the SAME structured context. ``render`` (graph.eval.show_*) toggles the temporal
    annotations and MUST be the same across the answer, judge, and evidence-check calls of one
    question, or the judge's evidence substring check no longer matches what the model saw. Empty
    ⇒ ``""`` (callers supply their own fallback)."""
    render = render or RecallRenderOptions()
    items = list(hits or [])
    if not items:
        return ""
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for hit in items:
        by_kind.setdefault(str(hit.get("kind") or "fact"), []).append(hit)
    sections: list[str] = []
    for kind, heading in _RECALL_SECTIONS:
        rows = by_kind.get(kind)
        if not rows:
            continue
        lines = "\n".join(f"- {_format_recall_item(h, render)}" for h in rows)
        # Headings are markdown ("### Relevant Facts") — no trailing colon.
        sections.append(f"{heading}\n{lines}")
    return "\n\n".join(sections)


def _provider_prefix(model_id: str) -> str:
    """Provider half of a ``provider:model`` id for the ledger's provider column (blank if bare)."""
    return model_id.partition(":")[0] if ":" in model_id else ""


async def _ledger_llm_node(
    sink: Any | None,
    node: str,
    model_id: str,
    *,
    input_preview: str,
    call: Any,
) -> Any:
    """Run one model call as a ledgered node under the active run, recording token usage.

    ``call`` is a 0-arg async callable returning ``(result, ai_message, output_preview, decision)``
    where ``ai_message`` carries ``usage_metadata`` (may be ``None``) and ``decision`` is an optional
    ``(kind, detail)`` tuple. Returns ``result``. With ``sink is None`` the call runs unledgered
    (tests / CLI)."""
    if sink is None:
        result, _ai, _preview, _decision = await call()
        return result

    # Shared usage extractor: pulls cached-read + reasoning tokens (nested in *_token_details), not
    # just the flat input/output counts — so eval rows price like every other LLM node.
    from hirocli.runtime.agent_graph.base import _usage_from_metadata
    from hirocli.runtime.agent_graph.ledger import current_entry

    provider = _provider_prefix(model_id)
    # captures={"usage","decision"} is REQUIRED: without it to_row() blanks the entire usage +
    # decision block, so the row showed no model/tokens (and then priced off a now-blank model ⇒ no
    # cost). Mirrors how call_model / memory_search_node / the ingest nodes declare their captures.
    entry = sink.open_entry(node, {}, None, captures=frozenset({"usage", "decision"}))
    token = current_entry.set(entry)
    status, error_code = "ok", ""
    try:
        result, ai, output_preview, decision = await call()
        usage = _usage_from_metadata(getattr(ai, "usage_metadata", None) or {})
        entry.add_usage(
            provider=provider,
            # Store the FULL ``provider:model`` id (not the bare model) — the pricing catalog is
            # keyed by the prefixed id, so a bare model misses the catalog and prices as $0. This
            # mirrors call_model, which stores ``effective_model`` (the prefixed id) verbatim.
            model=model_id,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cached_input_tokens=usage.get("cached_input_tokens"),
            reasoning_tokens=usage.get("reasoning_tokens"),
        )
        if decision:
            entry.set_decision(*decision)
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


async def answer_from_context(
    model: Any,
    model_id: str,
    *,
    question: str,
    context: "list[dict[str, Any]]",
    sink: Any | None = None,
    instructions: str | None = None,
    render: RecallRenderOptions | None = None,
) -> str:
    """Brief answer to ``question`` grounded ONLY in ``context`` — the recalled hits as STRUCTURED
    rows (``{kind, memory, …metadata}``), rendered into Relevant Facts / Entities / Messages
    sections so the model sees each kind with its metadata (relationship, temporal validity, type).

    Message layout (the conv-43 P1/P4 prompt rework): the system prompt is the hardcoded two-line
    ``MEMORY_EVAL_ANSWER_SYSTEM_PROMPT`` role; ``instructions`` (the editable
    ``graph.eval.memory_answer_prompt`` pref, blank ⇒ ``DEFAULT_MEMORY_EVAL_ANSWER_PROMPT``) goes
    in the USER message, followed by "## User Question" and "## Recalled Memory Elements" — the
    question precedes the context so the model reads the elements knowing the target.

    Ledgered as an ``eval_answer`` node. Empty context ⇒ the model is asked over no elements, so it
    should decline (tests memory recall honestly)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from hirocli.runtime.agent_graph.base import _normalize_reply_content

    instr = (instructions or "").strip() or DEFAULT_MEMORY_EVAL_ANSWER_PROMPT
    recalled = format_recall_context(context, render) or "(no elements recalled)"
    human = (
        f"{instr}\n\n"
        f"## User Question\n{question}\n\n"
        f"## Recalled Memory Elements\n{recalled}"
    )

    async def _call() -> tuple[str, Any, str, tuple[str, str]]:
        # ``run_name`` labels this LLM call as ``eval_answer`` in LangSmith (under the
        # ``eval_question`` span), so the answering step is distinguishable from the judge.
        ai = await model.ainvoke(
            [SystemMessage(MEMORY_EVAL_ANSWER_SYSTEM_PROMPT), HumanMessage(human)],
            config={"run_name": "eval_answer"},
        )
        # Flatten provider content (Anthropic returns a list of text blocks) to plain text;
        # str() on the raw list leaked a JSON-ish repr into the recall answer. Reuse the
        # shared agent-graph normalizer instead of duplicating block-extraction here.
        text = _normalize_reply_content(getattr(ai, "content", "")).strip()
        # Decision surfaces whether the model answered or declined. Two decline phrases: the new
        # default's "No information available." (LoCoMo's negative-control convention) plus the
        # legacy "I don't know" so a custom prompt pref still using it keeps detecting.
        low = text.lower()
        declined = low.startswith("no information available") or low.startswith("i don't know")
        decision = ("abstained", "no_context") if declined else ("answered", "grounded")
        return text, ai, text[:200], decision

    return await _ledger_llm_node(
        sink, "eval_answer", model_id, input_preview=f"q: {question[:160]}", call=_call
    )


def _normalize_text(text: str) -> str:
    """Lowercase + collapse whitespace, for a forgiving evidence/context substring match."""
    return " ".join((text or "").lower().split())


def _evidence_supported(
    evidence: str,
    context: "list[dict[str, Any]] | None",
    render: RecallRenderOptions | None = None,
) -> bool:
    """Whether the judge's quoted ``evidence`` actually occurs in the recalled ``context``.

    Whitespace/case-insensitive substring match against both the rendered context block AND each
    recalled item's ``memory`` text (a flat judge may quote one item rather than the whole block).
    Empty evidence ⇒ unsupported. This is the deterministic backstop that stops the judge from
    claiming ``recall_sufficient`` without grounding (the locomo conv-43 false positives).
    ``render`` MUST match what the judge saw so the block-level match uses the same annotations."""
    ev = _normalize_text(evidence)
    if not ev:
        return False
    if ev in _normalize_text(format_recall_context(context, render)):
        return True
    return any(ev in _normalize_text(str(h.get("memory") or "")) for h in (context or []))


async def judge_answer(
    model: Any,
    model_id: str,
    *,
    question: str,
    answer: str,
    expected_answer: str,
    context: "list[dict[str, Any]] | None" = None,
    is_negative_control: bool = False,
    sink: Any | None = None,
    system_prompt: str | None = None,
    render: RecallRenderOptions | None = None,
) -> JudgeVerdict:
    """Grade ``answer`` against the ideal ``expected_answer`` → :class:`JudgeVerdict`.

    ``context`` is the SAME structured recalled hits the answerer saw; the judge uses it only to
    set ``recall_sufficient`` (recall-miss vs answering-miss), never to shift the verdict (which is
    measured against the IDEAL). ``None`` (e.g. the knowledge track) ⇒ no context section,
    ``recall_sufficient`` defaults true.

    ``system_prompt`` is the editable ``graph.eval.judge_prompt`` pref; blank falls back to
    ``DEFAULT_MEMORY_EVAL_JUDGE_PROMPT``. When context IS present, ``recall_sufficient`` is then
    backstopped: the judge must quote a context line in ``evidence`` (verified by substring) or it
    is forced to ``False`` — killing ungrounded sufficiency claims.

    Ledgered as an ``eval_judge`` node. Falls back to a ``fail`` verdict (not an exception) if the
    judge call errors, so one bad grade never aborts the run."""
    from langchain_core.messages import HumanMessage, SystemMessage

    # Provider-aware structured output: DeepSeek thinking mode 400s on the default forced
    # tool_choice, so the compat helper switches it to json_mode (the judge prompt's Output Fields
    # section carries the schema, which json_mode needs since field descriptions don't reach it).
    from hirocli.domain.model_factory import with_structured_output_compat

    sys_prompt = (system_prompt or "").strip() or DEFAULT_MEMORY_EVAL_JUDGE_PROMPT
    control = "YES — declining is the correct outcome." if is_negative_control else "no"
    recalled = format_recall_context(context, render)
    # Model Answer BEFORE the recalled elements: the verdict is Answer-vs-Ideal, so the judge
    # meets the graded material first; the elements are auxiliary (evidence/recall_sufficient).
    context_block = (
        f"\n\n## Recalled Memory Elements (shown to the answerer)\n{recalled}" if recalled else ""
    )
    human = (
        f"## Question\n{question}\n\n"
        f"## Ideal Answer\n{expected_answer or '(none given)'}\n\n"
        f"## Negative Control\n{control}\n\n"
        f"## Model Answer\n{answer or '(empty)'}"
        f"{context_block}"
    )
    structured = with_structured_output_compat(model, _JudgeOutput, include_raw=True)

    async def _call() -> tuple[JudgeVerdict, Any, str, tuple[str, str]]:
        # ``run_name`` labels this LLM call as ``eval_judge`` in LangSmith, so the grading step
        # is distinguishable from the answering step under the same ``eval_question`` span.
        raw = await structured.ainvoke(
            [SystemMessage(sys_prompt), HumanMessage(human)],
            config={"run_name": "eval_judge"},
        )
        parsed: _JudgeOutput | None = raw.get("parsed") if isinstance(raw, dict) else raw
        ai = raw.get("raw") if isinstance(raw, dict) else None
        verdict_word = str(getattr(parsed, "verdict", "") or "").strip().lower()
        mark = _VERDICT_TO_MARK.get(verdict_word, MARK_FAIL)
        reason = str(getattr(parsed, "reason", "") or "").strip()
        grounded = bool(getattr(parsed, "grounded", True))
        recall_sufficient = bool(getattr(parsed, "recall_sufficient", True))
        # Verify the judge's quote is a real recalled line. Only a verified-present quote is kept as
        # `evidence` (so the UI never shows a hallucinated quote); an unverifiable quote is dropped.
        evidence_raw = str(getattr(parsed, "evidence", "") or "").strip()
        evidence = (
            evidence_raw if (context and _evidence_supported(evidence_raw, context, render)) else ""
        )
        # Backstop: recall_sufficient may only stand if that quote checked out — catches flat-model
        # false positives that CLAIM the context was sufficient without grounding (locomo conv-43).
        # Only when context was shown; the knowledge track passes none, so its default-true stands.
        if recall_sufficient and context and not evidence:
            log.info(
                "⚠️ knowledge.eval.judge — ungrounded recall_sufficient → False · q=%s",
                question[:80],
            )
            recall_sufficient = False
        verdict = JudgeVerdict(
            mark=mark,
            reason=reason,
            grounded=grounded,
            recall_sufficient=recall_sufficient,
            evidence=evidence,
        )
        # Decision detail carries the verdict word so the ledger row reads at a glance (e.g. graded/pass).
        return verdict, ai, f"{mark} {reason[:120]}", ("graded", verdict_word or "fail")

    try:
        return await _ledger_llm_node(
            sink, "eval_judge", model_id, input_preview=f"q: {question[:120]}", call=_call
        )
    except Exception:
        log.warning("⚠️ knowledge.eval — judge call failed · q=%s", question[:80], exc_info=True)
        return JudgeVerdict(mark=MARK_FAIL, reason="judge error", grounded=False)


__all__ = [
    "JudgeVerdict",
    "MEMORY_EVAL_ANSWER_SYSTEM_PROMPT",
    "RecallRenderOptions",
    "answer_from_context",
    "format_recall_context",
    "judge_answer",
]
