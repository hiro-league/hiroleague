"""Eval data models + model factories.

The unified per-question/per-leg result shapes (``LegResult`` / ``QuestionResult`` /
``EvalSummary``) both runners produce, the selectable retrieval-leg set, and the eval
chat-model builders (answer + judge each have their OWN preference-resolved model).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from hirocli.services.eval.events import _preview

log = Logger.get("SVC.KNOWLEDGE.EVAL")


# The selectable eval legs (retrieval modes). "flat" = no graph (Qdrant hybrid);
# "graphiti" = graph facts + their episode chunks by-id (no query hybrid). Either
# leg is runnable on its own. Order here is the canonical column order in the UI.
ALL_EVAL_MODES: tuple[str, ...] = ("flat", "graphiti")
DEFAULT_EVAL_MODES: list[str] = list(ALL_EVAL_MODES)


def normalize_modes(modes: list[str] | None) -> list[str]:
    """Validate + order a requested leg subset; fall back to all legs.

    Drops unknown names, de-dupes, and preserves the canonical column order so the
    UI columns are stable regardless of selection order. Empty/invalid → all legs."""
    if not modes:
        return list(DEFAULT_EVAL_MODES)
    wanted = {m for m in modes if m in ALL_EVAL_MODES}
    ordered = [m for m in ALL_EVAL_MODES if m in wanted]
    return ordered or list(DEFAULT_EVAL_MODES)


@dataclass(frozen=True)
class LegResult:
    """One leg's outcome for a single question (unified across tracks).

    ``mode`` is the leg name: ``flat``/``graphiti`` (knowledge) or ``recall`` (memory).
    ``mark`` is the LLM-judge verdict glyph (``""`` when the judge was off — answers only).
    ``recalled`` carries the memory engine's facts (empty for knowledge legs)."""

    mode: str
    mark: str          # one of MARK_* (or "" when not judged)
    elapsed_ms: int
    answer: str        # the model's answer
    run_id: str | None
    reason: str = ""   # judge's one-line justification
    recalled: tuple[Any, ...] = ()  # memory: the recalled facts (structured rows for the table)
    cost_usd: float = 0.0  # this leg's folded LLM+reranker cost (read from its run; 0 if unknown)
    # Judge extras (shown on the highlighted judge line): was the answer grounded in the context,
    # and did the recalled context actually contain what was needed (recall-miss vs answering-miss).
    grounded: bool = True
    recall_sufficient: bool = True
    # The recalled line(s) the judge quoted as supporting the answer (verified present; "" otherwise).
    # Surfaced in the eval UI's Judge section. Memory recall leg only — knowledge legs pass no context.
    evidence: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "mark": self.mark,
            "elapsed_ms": self.elapsed_ms,
            "answer_preview": _preview(self.answer, 200),
            "answer": self.answer,
            "run_id": self.run_id,
            "reason": self.reason,
            "recalled": list(self.recalled),
            "cost_usd": self.cost_usd,
            "grounded": self.grounded,
            "recall_sufficient": self.recall_sufficient,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class QuestionResult:
    """Per-question outcome across the selected legs."""

    id: str
    category: str
    question: str
    requires_graph: bool
    # Leg name → that leg's result. ``flat``/``graphiti`` (knowledge) or ``recall`` (memory).
    legs: dict[str, LegResult]
    # Best graph leg vs flat, as a signed rank delta (knowledge Δ column). "0" otherwise.
    delta: str
    subcategory: str = ""
    # Authored difficulty (medium/hard/very_hard); "" when the corpus omits it. Reporting-only.
    difficulty: str = ""
    track: str = "knowledge"
    # The ideal answer the judge graded against (shown as "Ideal" in results).
    gold: str = ""
    # Whole-question cost (sum of leg runs + judge run) — what the UI sums for the live total.
    cost_usd: float = 0.0
    # Negative control (expected_kind: abstain) — abstaining is the correct outcome here, so the
    # scoring helpers count an abstain as correct ONLY when this is true.
    is_negative_control: bool = False
    # ISO-8601 UTC timestamp when this question finished evaluating (for the "Time" column).
    answered_at: str = ""

    def to_payload(self, *, index: int, total: int) -> dict[str, Any]:
        """Event payload shape consumed by the Eval Batch UI. ``legs`` is keyed by leg name
        so the panel renders one column/section per leg; full answers are inlined (small)."""
        return {
            "index": index,
            "total": total,
            "id": self.id,
            "category": self.category,
            "subcategory": self.subcategory,
            "difficulty": self.difficulty,
            "question": self.question,
            "requires_graph": self.requires_graph,
            "track": self.track,
            "gold": self.gold,
            "cost_usd": self.cost_usd,
            "is_negative_control": self.is_negative_control,
            "answered_at": self.answered_at,
            "legs": {mode: leg.to_payload() for mode, leg in self.legs.items()},
            "delta": self.delta,
        }


@dataclass
class EvalSummary:
    """Aggregate output of one eval run — the gate verdict's evidence."""

    run_id: str
    total_questions: int
    modes: list[str]
    # leg name → number of CORRECT rows (pass, or abstain on a negative control).
    passing: dict[str, int]
    requires_graph_total: int
    # leg name → passing rows within the requires_graph subset.
    requires_graph_passing: dict[str, int]
    gate: str  # "proceed" | "pivot" | "n/a"
    elapsed_ms: int
    # Whether the LLM judge ran (marks present). When false, the table shows answers only.
    judged: bool = True
    track: str = "knowledge"
    questions: list[QuestionResult] = field(default_factory=list)
    # category → {total, pass: {leg: count}} — the per-category × N-leg table.
    by_category: dict[str, dict[str, Any]] = field(default_factory=dict)
    # difficulty → {total, groups/correct/score per leg} — same shape, bucketed by difficulty.
    by_difficulty: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Overall per-leg answer-mark distribution {leg: {pass, partial, fail, abstain}} and the
    # graded score {leg: float} (correct + 0.5·partial) — drive the summary card's metrics.
    groups: dict[str, dict[str, int]] = field(default_factory=dict)
    scoring: dict[str, float] = field(default_factory=dict)
    # Cost (LLM + reranker; embeddings unpriced). Knowledge ingest cost is deferred (multi-run)
    # so ``ingest_cost_usd`` stays 0 here; ``questions_cost_usd`` = sum of per-question costs.
    questions_cost_usd: float = 0.0
    ingest_cost_usd: float = 0.0

    def to_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "track": self.track,
            "total_questions": self.total_questions,
            "modes": self.modes,
            "passing": self.passing,
            "requires_graph_total": self.requires_graph_total,
            "requires_graph_passing": self.requires_graph_passing,
            "gate": self.gate,
            "judged": self.judged,
            "elapsed_ms": self.elapsed_ms,
            "by_category": self.by_category,
            "by_difficulty": self.by_difficulty,
            "groups": self.groups,
            "scoring": self.scoring,
            "questions_cost_usd": self.questions_cost_usd,
            "ingest_cost_usd": self.ingest_cost_usd,
            "total_cost_usd": self.questions_cost_usd + self.ingest_cost_usd,
        }


def _build_eval_model(workspace_path: Path, *, which: str) -> tuple[Any | None, str]:
    """Resolve + build an eval chat model. ``which`` picks the role — ``'answer'`` (the memory-eval
    answer step), ``'judge'`` (the LLM judge, both tracks), or ``'retrieval'`` (the agentic
    retrieval loop) — each with its OWN model + tuning profile preference (``graph.eval.answer_*``
    / ``graph.eval.judge_*`` / ``graph.eval.retrieval_*``). Returns ``(model, model_id)`` or
    ``(None, "")`` when unconfigured/unavailable so callers skip that step gracefully."""
    try:
        from hirocli.domain.model_factory import create_chat_model
        from hirocli.domain.preferences import (
            load_preferences,
            resolve_eval_answer_llm,
            resolve_eval_judge_llm,
            resolve_eval_retrieval_llm,
        )

        prefs = load_preferences(workspace_path)
        resolver = {
            "answer": resolve_eval_answer_llm,
            "judge": resolve_eval_judge_llm,
            "retrieval": resolve_eval_retrieval_llm,
        }[which]
        spec = resolver(prefs, workspace_path)
        if spec is None:
            log.warning("⚠️ knowledge.eval — no eval %s model configured; skipping it", which)
            return None, ""
        model = create_chat_model(
            spec.model_id,
            workspace_path=workspace_path,
            temperature=spec.temperature,
            max_tokens=spec.max_tokens,
            thinking=spec.thinking,
        )
        return model, spec.model_id
    except Exception:
        log.warning("⚠️ knowledge.eval — eval %s model unavailable", which, exc_info=True)
        return None, ""


def build_eval_answer_model(workspace_path: Path) -> tuple[Any | None, str]:
    """The memory-eval ANSWER model (``graph.eval.answer_model`` + tuning). See ``_build_eval_model``."""
    return _build_eval_model(workspace_path, which="answer")


def build_eval_judge_model(workspace_path: Path) -> tuple[Any | None, str]:
    """The eval JUDGE model (``graph.eval.judge_model`` + tuning). See ``_build_eval_model``."""
    return _build_eval_model(workspace_path, which="judge")


def build_eval_retrieval_model(workspace_path: Path) -> tuple[Any | None, str]:
    """The agentic-retrieval model (``graph.eval.retrieval_model`` + tuning; falls back to the
    answer model when unset). See ``_build_eval_model``."""
    return _build_eval_model(workspace_path, which="retrieval")
