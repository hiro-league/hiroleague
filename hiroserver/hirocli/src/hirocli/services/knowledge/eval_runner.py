"""Eval runner — in-process orchestrator that publishes per-question events.

Loads a corpus, ingests/remembers it, runs each question, scores (knowledge) or
collects recalled facts (memory), and summarizes — as an **awaitable function that
publishes Domain Events as it goes**, so the admin Eval Batch UI updates the table
live via the existing ``/knowledge/events`` SSE stream. This in-process runner is the
only eval entry point (the old standalone CLI harness was retired).

Event types published (see ``constants.py``):

* ``knowledge.eval.started`` — once, at the start, with run_id + total_questions
* ``knowledge.eval.setup_progress`` — during setup (ingest synthetic / build graph)
* ``knowledge.eval.question_completed`` — once per question with both legs scored
* ``knowledge.eval.completed`` — once, with summary + gate verdict
* ``knowledge.eval.failed`` — once on uncaught exception (run aborted)
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from hiro_commons.log import Logger

from hirocli.domain.events import DomainEvent, get_domain_event_bus
from hirocli.services.knowledge.graph.group_scope import (
    eval_memory_group_id,
    slug_group_part,
)
from hirocli.services.knowledge.constants import (
    KNOWLEDGE_EVAL_COMPLETED,
    KNOWLEDGE_EVAL_FAILED,
    KNOWLEDGE_EVAL_QUESTION_COMPLETED,
    KNOWLEDGE_EVAL_SETUP_PROGRESS,
    KNOWLEDGE_EVAL_STARTED,
)
from hirocli.services.knowledge.eval_scoring import (
    MARK_ABSTAIN,
    MARK_PASS,
    MARK_RANK,
)

# A row "passes" for aggregate counting when it's correct (pass) or correctly
# abstained (the right outcome on negative-control / abstention rows).
_PASSING_MARKS = (MARK_PASS, MARK_ABSTAIN)

log = Logger.get("SVC.KNOWLEDGE.EVAL")


# Default corpus + questions location relative to repo root (eval/ at top level).
# The runner takes these as parameters so tests can point at fixtures, but the
# Tool defaults to these paths when the caller doesn't override.
_REPO_ROOT = Path(__file__).resolve().parents[6]  # services/knowledge → … → hiroleague repo
DEFAULT_CORPUS_DIR = _REPO_ROOT / "eval" / "l3_synthetic"
DEFAULT_QUESTIONS_FILE = _REPO_ROOT / "eval" / "l3_synthetic.questions.yaml"
# The repo's bundled corpora live here; the admin corpus picker defaults to it but any
# folder can be scanned (docs/eval-corpus-tracks-design.md §12). Stem convention:
#   memory:    <name>.episodes.jsonl   ↔  <name>.questions.yaml
#   knowledge: <name>/ (a folder of .md) ↔ <name>.questions.yaml (sibling)
DEFAULT_EVAL_FOLDER = _REPO_ROOT / "eval"


# Tag auto-applied to ingested eval docs so flat/graph retrieval can be scoped
# to ONLY the synthetic corpus (so the eval comparison stays fair even when the
# workspace has unrelated knowledge docs already ingested). See plan §5f.
EVAL_SYNTHETIC_TAG = "_l3_eval_synthetic"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


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
    recalled: tuple[str, ...] = ()  # memory: the recalled facts (for the fold/detail)

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
    track: str = "knowledge"
    # The ideal answer the judge graded against (shown as "Ideal" in results).
    gold: str = ""
    must_not_contain: list[str] = field(default_factory=list)

    def to_payload(self, *, index: int, total: int) -> dict[str, Any]:
        """Event payload shape consumed by the Eval Batch UI. ``legs`` is keyed by leg name
        so the panel renders one column/section per leg; full answers are inlined (small)."""
        return {
            "index": index,
            "total": total,
            "id": self.id,
            "category": self.category,
            "subcategory": self.subcategory,
            "question": self.question,
            "requires_graph": self.requires_graph,
            "track": self.track,
            "gold": self.gold,
            "legs": {mode: leg.to_payload() for mode, leg in self.legs.items()},
            "delta": self.delta,
            "must_not_contain": self.must_not_contain,
        }


@dataclass
class EvalSummary:
    """Aggregate output of one eval run — the gate verdict's evidence."""

    run_id: str
    total_questions: int
    modes: list[str]
    # leg name → number of passing rows (pass or correct-abstain).
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
        }


# ---------------------------------------------------------------------------
# Public surfaces
# ---------------------------------------------------------------------------


def load_questions(path: Path | None = None) -> list[dict[str, Any]]:
    """Load + validate the eval questions YAML.

    Each row needs ``id`` + ``question`` and a grading reference — **either** an
    ``expected_answer`` (the ideal answer the LLM judge grades against) **or**
    ``expected_kind: abstain`` (negative control). ``expected_fragments`` is now optional
    (substring scoring was dropped in favor of the judge) but still parsed when present.
    Extra keys (category, requires, notes) pass through."""
    target = path or DEFAULT_QUESTIONS_FILE
    if not target.exists():
        raise FileNotFoundError(f"L3 eval questions not found: {target}")
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{target}: expected a non-empty list of questions")
    out: list[dict[str, Any]] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"{target}: row {i} is not a mapping")
        qid = str(row.get("id") or "").strip()
        qtext = str(row.get("question") or "").strip()
        if not qid or not qtext:
            raise ValueError(f"{target}: row {i} missing id or question")
        # ``expected_kind: abstain`` = negative control (abstaining is the correct outcome).
        expected_kind = str(row.get("expected_kind") or "").strip().lower()
        has_fragments_key = "expected_fragments" in row
        expected = row.get("expected_fragments")
        expected = expected if isinstance(expected, list) else []
        gold = str(row.get("expected_answer") or "").strip()
        # A negative control: explicit abstain, or an explicit empty fragments list with no gold
        # (the legacy "[] = abstain is correct" shorthand).
        negative = expected_kind == "abstain" or (has_fragments_key and not expected and not gold)
        # Grading reference required: a gold answer, a negative control, or legacy fragments.
        if not gold and not expected and not negative:
            raise ValueError(
                f"{target}: row {i} ({qid}): needs an `expected_answer` (judge reference), "
                f"`expected_kind: abstain`, or `expected_fragments`"
            )
        if negative:
            expected_kind = "abstain"
        must_not = row.get("must_not_contain") or []
        if not isinstance(must_not, list):
            raise ValueError(f"{target}: row {i} ({qid}): must_not_contain must be a list")
        # requires_graph: explicit bool OR derived from a ``requires`` list that names
        # graph/temporal/world (those categories are where graph/mix should win).
        requires_raw = row.get("requires") or []
        requires_list = requires_raw if isinstance(requires_raw, list) else []
        requires_graph = bool(row.get("requires_graph")) or any(
            str(r).strip().lower() in ("graph", "temporal", "world") for r in requires_list
        )
        out.append(
            {
                "id": qid,
                "category": str(row.get("category") or ""),
                "subcategory": str(row.get("subcategory") or ""),
                "question": qtext,
                "expected_fragments": [str(f) for f in expected],
                "must_not_contain": [str(f) for f in must_not],
                "requires_graph": requires_graph,
                # The ideal answer the LLM judge grades against (shown as "Ideal" in results).
                "expected_answer": gold,
                # "abstain" ⇒ negative control: abstaining is the correct outcome.
                "expected_kind": expected_kind,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Corpus discovery — scan a folder, pair corpuses with their question banks
# ---------------------------------------------------------------------------
#
# A corpus is identified by (track, folder, id). Stem convention (docs §12):
#   memory:    <id>.episodes.jsonl    ↔ <id>.questions.yaml
#   knowledge: <id>/ (folder of .md)  ↔ <id>.questions.yaml (sibling of the folder)
# id doubles as the eval drawer suffix → eval_mem_<id> / eval_kb_<id>.


def _safe_question_count(questions_path: Path) -> int:
    """Best-effort question count for the picker; 0 when the bank is missing/unreadable."""
    if not questions_path.exists():
        return 0
    try:
        return len(load_questions(questions_path))
    except Exception:
        # A malformed bank shouldn't break corpus discovery — surface 0 and let the run
        # fail loud later if the user picks it.
        log.warning("⚠️ knowledge.eval — unreadable question bank · path=%s", questions_path, exc_info=True)
        return 0


def discover_corpuses(folder: Path | str, track: str) -> list[dict[str, Any]]:
    """List the corpuses in ``folder`` for ``track`` (``memory`` | ``knowledge``).

    Each entry: ``{id, name, corpus_path, questions_path, question_count, item_count}``
    where ``item_count`` is episodes (memory) or ``.md`` docs (knowledge). Returns ``[]``
    for a missing/empty folder (the picker shows a hint, not an error)."""
    base = Path(folder)
    if not base.exists() or not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    if track == "memory":
        for f in sorted(base.glob("*.episodes.jsonl")):
            if "bak" in f.stem.lower():  # skip *.episodes_bak backups
                continue
            stem = f.name[: -len(".episodes.jsonl")]
            qpath = base / f"{stem}.questions.yaml"
            episodes = 0
            try:
                from hirocli.services.knowledge.graph.graphiti_corpus import load_episodes_file

                episodes = len(load_episodes_file(f))
            except Exception:
                log.warning("⚠️ knowledge.eval — unreadable corpus · path=%s", f, exc_info=True)
            out.append(
                {
                    "id": stem,
                    "name": stem,
                    "corpus_path": str(f),
                    "questions_path": str(qpath) if qpath.exists() else "",
                    "question_count": _safe_question_count(qpath),
                    "item_count": episodes,
                }
            )
    else:  # knowledge — a corpus is a subfolder of .md docs
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            md = list(d.glob("*.md"))
            if not md:
                continue
            qpath = base / f"{d.name}.questions.yaml"
            out.append(
                {
                    "id": d.name,
                    "name": d.name,
                    "corpus_path": str(d),
                    "questions_path": str(qpath) if qpath.exists() else "",
                    "question_count": _safe_question_count(qpath),
                    "item_count": len(md),
                }
            )
    return out


def build_answer_model(workspace_path: Path) -> tuple[Any | None, str]:
    """Resolve + build the workspace **answering model** for the eval answer/judge steps
    (reused, not a separate eval model). Returns ``(model, model_id)`` or ``(None, "")`` when
    no answering model is configured — callers then skip answer/judge gracefully."""
    try:
        from hirocli.domain.model_factory import create_chat_model
        from hirocli.domain.preferences import (
            load_preferences,
            resolve_knowledge_answering_llm,
        )

        prefs = load_preferences(workspace_path)
        spec = resolve_knowledge_answering_llm(prefs, workspace_path)
        if spec is None:
            log.warning("⚠️ knowledge.eval — no answering model configured; skipping answer/judge")
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
        log.warning("⚠️ knowledge.eval — answering model unavailable for answer/judge", exc_info=True)
        return None, ""


async def run_eval(
    service: Any,
    workspace_path: Path,
    *,
    questions: list[dict[str, Any]] | None = None,
    run_id: str | None = None,
    filters: dict[str, Any] | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
    modes: list[str] | None = None,
    judge: bool = False,
) -> EvalSummary:
    """Run the question loop against ``service`` — emitting events as it goes.

    Assumes the synthetic corpus + graph are already ingested. (Setup is a
    separate concern; the Tool wraps both.)

    Each question runs via ``service.compare`` so both legs (flat / graph)
    share the same query/rewrite/embedder/rerank — only ``use_graph`` differs.
    The filter (``tags=["_l3_eval_synthetic"]`` by default) scopes retrieval
    to the synthetic corpus so unrelated workspace docs don't pollute results.

    ``run_id`` is generated if not provided; events carry it so the UI can
    correlate event stream → row updates.
    """
    bus = get_domain_event_bus()
    rid = run_id or f"l3eval-{uuid.uuid4()}"
    questions = questions if questions is not None else load_questions()
    total = len(questions)
    run_modes = normalize_modes(modes)
    started_at = time.perf_counter()

    # Default the synthetic-tag filter unless the caller passed their own.
    eval_filters: dict[str, Any] = dict(filters or {})
    eval_filters.setdefault("tags", [EVAL_SYNTHETIC_TAG])

    # Optional LLM judge: build the answering model + a ledger sink (so judge calls show as
    # priced Graph Runs). When the judge is off — or no model is configured — legs carry the
    # answer but no mark, and the gate is n/a.
    model, model_id = (build_answer_model(workspace_path) if judge else (None, ""))
    sink = None
    if model is not None:
        from hirocli.runtime.agent_graph.ledger import LedgerSink

        sink = LedgerSink(workspace_path)
    judged = model is not None

    _publish(
        bus,
        workspace_path,
        KNOWLEDGE_EVAL_STARTED,
        {
            "run_id": rid,
            "total_questions": total,
            "track": "knowledge",
            "filters": eval_filters,
            # Selected legs — the UI needs these up front to render the right
            # columns before the first question row arrives.
            "modes": run_modes,
            "judged": judged,
        },
    )

    rows: list[QuestionResult] = []
    try:
        for index, q in enumerate(questions):
            result = await _run_one_question(
                service,
                q,
                modes=run_modes,
                filters=eval_filters,
                top_k=top_k,
                min_score=min_score,
                model=model,
                model_id=model_id,
                judge=judged,
                sink=sink,
                run_id=rid,
            )
            rows.append(result)
            # run_id on every event so the per-workspace registry can attribute
            # this row to the right run (the registry replays state on mount /
            # cross-origin; see eval_registry.py).
            _publish(
                bus,
                workspace_path,
                KNOWLEDGE_EVAL_QUESTION_COMPLETED,
                {"run_id": rid, **result.to_payload(index=index, total=total)},
            )
    except Exception as exc:
        log.error(
            "❌ knowledge.eval — run aborted",
            run_id=rid,
            error=str(exc),
            exc_info=True,
        )
        _publish(
            bus,
            workspace_path,
            KNOWLEDGE_EVAL_FAILED,
            {"run_id": rid, "error": f"{type(exc).__name__}: {str(exc)[:200]}"},
        )
        raise

    summary = _summarize(rid, rows, started_at, run_modes, judged=judged)
    _publish(
        bus,
        workspace_path,
        KNOWLEDGE_EVAL_COMPLETED,
        summary.to_payload(),
    )
    return summary


# ---------------------------------------------------------------------------
# Setup helpers (called by the Tool when the caller asks for it)
# ---------------------------------------------------------------------------


async def ingest_synthetic_corpus_via_service(
    service: Any,
    workspace_path: Path,
    *,
    corpus_dir: Path | None = None,
    tag: str = EVAL_SYNTHETIC_TAG,
    run_id: str | None = None,
) -> list[str]:
    """Ingest the synthetic corpus into the workspace's knowledge index and
    return the freshly-ingested document_ids.

    Tags every ingested doc with the eval tag so retrieval can filter to the
    synthetic-only candidate set. Idempotent: re-running on the same workspace
    skips already-ingested docs via the existing content_hash dedup.
    """
    target = corpus_dir or DEFAULT_CORPUS_DIR
    paths = sorted(target.glob("*.md"))
    if not paths:
        raise FileNotFoundError(f"No .md files in synthetic corpus dir: {target}")

    bus = get_domain_event_bus()
    _publish(
        bus,
        workspace_path,
        KNOWLEDGE_EVAL_SETUP_PROGRESS,
        {"run_id": run_id, "phase": "ingest_synthetic", "file_count": len(paths)},
    )

    await service.ingest_and_wait(
        [str(p) for p in paths],
        owner_kind="system",
        owner_id="0",
        tags=[tag],
    )

    # Resolve back to document_ids by source_uri match.
    docs_result = await service.list_documents(limit=500, offset=0)
    ids: list[str] = []
    target_str = str(target.resolve())
    for doc in docs_result.documents:
        if str(doc.source_uri).startswith(target_str):
            ids.append(doc.id)
    return ids


# ---------------------------------------------------------------------------
# Memory eval track — turn corpus → conversation remember/recall (Phase 1)
#
# docs/eval-corpus-tracks-design.md §8. The Adam turn corpus now feeds the
# CONVERSATION-MEMORY engine (remember/recall), not the knowledge pipeline — a
# routing correction (Adam is turn-shaped data; turns belong in chat). Data lands
# in a dedicated ``eval_mem_{set}`` drawer via an eval-scoped GraphitiConversationMemory
# (the scoped-service-object), never a real ``mem_{user}_{character}`` group.
#
# We are in initial development → no backward compatibility: the prior
# Adam-through-knowledge path (Qdrant + kb_main double-write) is retired, not wrapped.
# ---------------------------------------------------------------------------

ADAM_CORPUS_FILE = _REPO_ROOT / "eval" / "adam_year.episodes.jsonl"
ADAM_QUESTIONS_FILE = _REPO_ROOT / "eval" / "adam_year.questions.yaml"

# Default memory-eval set id (the bundled Adam corpus stem) → the ``eval_mem_adam_year`` drawer.
DEFAULT_MEMORY_EVAL_SET = "adam_year"
# Nominal user id for the eval-scoped memory facade. The drawer is minted by the scope
# override (eval_mem_{set}), so this id never reaches a group_id (decision E-a, moot) — a
# negative sentinel keeps it from ever colliding with a real (positive) data.db user id.
MEMORY_EVAL_USER_ID = -1


def load_adam_questions(path: Path | None = None) -> list[dict[str, Any]]:
    """Load the Adam question bank (same validation as ``load_questions``)."""
    return load_questions(path or ADAM_QUESTIONS_FILE)


async def _remember_episodes(
    memory: Any,
    episodes: "list[Any]",
    *,
    workspace_path: Path,
    run_id: str,
    user_id: int,
    character_id: str,
    ledger_sink: Any | None = None,
) -> int:
    """Replay each episode through the ``remember`` path (one turn at a time, in
    chronological order so supersession resolves correctly). Emits a per-episode
    ``setup_progress`` line so the admin terminal ticks during the (LLM-bound) build.

    ``ledger_sink`` makes each turn's Graphiti extraction observable in **Graph Runs**:
    the caller opens one parent run (``current_run``) and passes its sink here, so every
    turn's per-episode/per-operation rows NEST under that single run (priced sub-rows fold
    into its aggregate). ``None`` ⇒ no ledger. Returns the facts learned across all turns."""
    bus = get_domain_event_bus()
    total = len(episodes)
    _publish(
        bus,
        workspace_path,
        KNOWLEDGE_EVAL_SETUP_PROGRESS,
        {"run_id": run_id, "phase": "remember", "episode_count": total},
    )
    learned = 0
    for index, ep in enumerate(episodes, start=1):
        ref = getattr(ep, "reference_time", None)
        meta = {
            "timestamp": ref.isoformat() if ref is not None else "",
            "speaker": getattr(ep, "speaker", "") or "User",
            "message_id": getattr(ep, "chunk_id", "") or "",
        }
        result = await memory.add(
            ep.text,
            user_id=user_id,
            run_id=f"eval:{run_id}",
            character_id=character_id,
            metadata=meta,
            ledger_sink=ledger_sink,
        )
        learned += int(getattr(result, "stored_count", 0) or 0)
        _publish(
            bus,
            workspace_path,
            KNOWLEDGE_EVAL_SETUP_PROGRESS,
            {
                "run_id": run_id,
                "phase": "remember",
                "index": index,
                "total": total,
                "snippet": _preview(ep.text, 90),
            },
        )
    return learned


async def _memory_question(
    memory: Any,
    q: dict[str, Any],
    *,
    user_id: int,
    character_id: str,
    sink: Any | None = None,
    run_id: str = "",
    set_id: str = "",
    model: Any | None = None,
    model_id: str = "",
    judge: bool = False,
) -> dict[str, Any]:
    """One memory question, all in ONE Graph Run: **recall** (graph search) → **answer**
    (grounded only in the recalled facts) → optional **judge** (vs the ideal answer).

    The run holds a ``memory_recall`` node (graph-search spans), an ``eval_answer`` node, and an
    ``eval_judge`` node — all priced. Returns the unified row (``legs={'recall': {...}}`` with the
    model answer + verdict mark + recalled facts, plus ``gold`` and the ``stale_hit`` guard)."""
    from hirocli.runtime.agent_graph.ledger import RunAccumulator, current_entry, current_run
    from hirocli.services.knowledge.eval_judge import answer_from_context, judge_answer
    from hirocli.services.knowledge.ledger_runner import preview_answer, preview_query

    must_not = q.get("must_not_contain") or []
    gold = q.get("expected_answer", "")
    is_control = str(q.get("expected_kind") or "") == "abstain"

    acc = None
    run_token = None
    if sink is not None:
        acc = RunAccumulator(
            sink=sink,
            run_id=f"memory_eval_q-{slug_group_part(set_id)}-{run_id}-{slug_group_part(str(q.get('id') or ''))}",
            inbound_id=eval_memory_group_id(set_id),
            character_id=set_id,
        )
        run_token = current_run.set(acc)

    facts: list[str] = []
    answer, mark, reason = "", "", ""
    t0 = time.perf_counter()
    try:
        # 1) recall (graph search) — ledgered as a memory_recall node when a sink is present.
        if sink is not None:
            entry = sink.open_entry("memory_recall", {}, None)
            entry_token = current_entry.set(entry)
            try:
                hits = await memory.search(
                    q["question"], user_id=user_id, character_id=character_id
                )
                facts = [
                    str(h.get("memory") or "") for h in hits if str(h.get("memory") or "").strip()
                ]
                entry.input_preview = preview_query(q["question"])
                entry.output_preview = preview_answer(" | ".join(facts) or "(nothing recalled)")
            finally:
                entry.finish("ok")
                sink.write_rows(entry.rows(include_parent=True))
                current_entry.reset(entry_token)
        else:
            hits = await memory.search(q["question"], user_id=user_id, character_id=character_id)
            facts = [
                str(h.get("memory") or "") for h in hits if str(h.get("memory") or "").strip()
            ]
        # 2) answer — grounded ONLY in the recalled facts (eval integrity).
        if model is not None:
            answer = await answer_from_context(
                model, model_id, question=q["question"], context=facts, sink=sink
            )
        # 3) judge — vs the ideal answer (optional step).
        if judge and model is not None:
            verdict = await judge_answer(
                model,
                model_id,
                question=q["question"],
                answer=answer,
                expected_answer=gold,
                must_not_contain=must_not,
                is_negative_control=is_control,
                sink=sink,
            )
            mark, reason = verdict.mark, verdict.reason
        if sink is not None and acc is not None:
            sink.write_run_row(
                acc,
                status="completed",
                decision_kind="completed",
                decision_detail="memory_eval_question",
                input_preview=f"q: {q['question'][:160]}",
                output_preview=(answer or " | ".join(facts))[:200],
            )
    finally:
        if run_token is not None and acc is not None:
            sink.evict_run(acc.run_id)
            current_run.reset(run_token)

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    blob = "\n".join(facts).lower()
    stale_hit = any(f.lower() in blob for f in must_not if f)
    return {
        "id": q["id"],
        "category": q.get("category", ""),
        "subcategory": q.get("subcategory", ""),
        "question": q["question"],
        "requires_graph": bool(q.get("requires_graph")),
        "track": "memory",
        "gold": gold,
        "must_not_contain": must_not,
        "stale_hit": stale_hit,
        "delta": "0",
        "legs": {
            "recall": {
                "mode": "recall",
                "mark": mark,
                "reason": reason,
                "elapsed_ms": elapsed_ms,
                "answer": answer,
                "answer_preview": _preview(answer, 200),
                "run_id": (acc.run_id if acc is not None else None),
                "recalled": facts,
            }
        },
    }


async def run_memory_eval(
    memory: Any,
    workspace_path: Path,
    *,
    set_id: str = DEFAULT_MEMORY_EVAL_SET,
    questions: list[dict[str, Any]] | None = None,
    episodes: "list[Any] | None" = None,
    corpus_path: Path | None = None,
    run_id: str | None = None,
    remember: bool = True,
    judge: bool = False,
    eval_user_id: int = MEMORY_EVAL_USER_ID,
) -> dict[str, Any]:
    """Run the memory-eval track: remember a turn corpus, then recall per question.

    Single engine (recall), no flat/graph comparison, no PROCEED/PIVOT gate (docs §8).
    Emits the shared ``knowledge.eval.*`` events with a ``track="memory"`` discriminator
    so the existing registry/SSE/replay infra carries it unchanged. ``memory`` must be an
    **eval-scoped** facade (its writes/reads target ``eval_mem_{set}``); the caller owns
    its lifecycle (build + close).

    Returns the summary payload (also published as ``knowledge.eval.completed``)."""
    from hirocli.services.knowledge.graph.graphiti_corpus import load_episodes_file

    bus = get_domain_event_bus()
    rid = run_id or f"memeval-{uuid.uuid4()}"
    questions = questions if questions is not None else load_adam_questions()
    total = len(questions)
    # character_id is cosmetic for an eval-scoped facade (the override mints the drawer),
    # but the MemoryService API requires one; the set id is the natural label.
    character_id = set_id
    started_at = time.perf_counter()

    # One ledger sink for the whole eval → the remember/build shows as ONE Graph Run and each
    # recall shows as its own retrieve run, mirroring the knowledge track (ingest run + per-question
    # answer runs). Lazy import keeps the ledger off this module's base import path.
    from hirocli.runtime.agent_graph.ledger import LedgerSink, RunAccumulator, current_run

    sink = LedgerSink(workspace_path)
    # Answer step uses the workspace answering model (reused). The judge (optional) grades it.
    model, model_id = build_answer_model(workspace_path)
    judged = judge and model is not None

    _publish(
        bus,
        workspace_path,
        KNOWLEDGE_EVAL_STARTED,
        {
            "run_id": rid,
            "total_questions": total,
            "track": "memory",
            "modes": ["recall"],
            "judged": judged,
            "filters": {"set": set_id},
        },
    )

    rows: list[dict[str, Any]] = []
    try:
        remembered = 0
        if remember:
            eps = episodes if episodes is not None else load_episodes_file(
                corpus_path or ADAM_CORPUS_FILE
            )
            # Open ONE parent run so every turn's Graphiti extraction nests under it (priced
            # sub-rows fold into the aggregate) — the memory "ingest" Graph Run.
            ledger_run_id = f"memory_eval-{slug_group_part(set_id)}-{rid}"
            accumulator = RunAccumulator(
                sink=sink,
                run_id=ledger_run_id,
                inbound_id=eval_memory_group_id(set_id),
                character_id=set_id,
            )
            token = current_run.set(accumulator)
            try:
                remembered = await _remember_episodes(
                    memory,
                    eps,
                    workspace_path=workspace_path,
                    run_id=rid,
                    user_id=eval_user_id,
                    character_id=character_id,
                    ledger_sink=sink,
                )
                sink.write_run_row(
                    accumulator,
                    status="completed",
                    decision_kind="completed",
                    decision_detail="memory_eval_remember",
                    input_preview=f"corpus: {set_id} ({len(eps)} turns)",
                    output_preview=f"remembered {len(eps)} turns · learned {remembered} facts",
                )
            finally:
                sink.evict_run(ledger_run_id)
                current_run.reset(token)
        for index, q in enumerate(questions):
            # Each question is its own Graph Run: recall → answer → (judge).
            row = await _memory_question(
                memory,
                q,
                user_id=eval_user_id,
                character_id=character_id,
                sink=sink,
                run_id=rid,
                set_id=set_id,
                model=model,
                model_id=model_id,
                judge=judged,
            )
            rows.append(row)
            _publish(
                bus,
                workspace_path,
                KNOWLEDGE_EVAL_QUESTION_COMPLETED,
                {"run_id": rid, "index": index, "total": total, **row},
            )
    except Exception as exc:
        # CancelledError is a BaseException (not Exception) → it propagates past this
        # handler to the route's cancel path, exactly as run_eval relies on.
        log.error(
            "❌ knowledge.eval — memory run aborted",
            run_id=rid,
            error=str(exc),
            exc_info=True,
        )
        _publish(
            bus,
            workspace_path,
            KNOWLEDGE_EVAL_FAILED,
            {"run_id": rid, "error": f"{type(exc).__name__}: {str(exc)[:200]}"},
        )
        raise

    def _recall_leg(r: dict[str, Any]) -> dict[str, Any]:
        return (r.get("legs") or {}).get("recall") or {}

    passing_recall = sum(1 for r in rows if _recall_leg(r).get("mark") in _PASSING_MARKS)
    summary = {
        "run_id": rid,
        "track": "memory",
        "total_questions": total,
        "modes": ["recall"],
        "judged": judged,
        "remembered_turns": remembered,
        "recalled_for": sum(1 for r in rows if _recall_leg(r).get("recalled")),
        "stale_hits": sum(1 for r in rows if r.get("stale_hit")),
        # Judge pass-count for the single recall leg (0 when the judge was off).
        "passing": {"recall": passing_recall},
        # No flat/graph legs → the PROCEED/PIVOT gate is undefined for the memory track.
        "gate": "n/a",
        "by_category": category_breakdown_rows(rows, ["recall"]),
        "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
    }
    _publish(bus, workspace_path, KNOWLEDGE_EVAL_COMPLETED, summary)
    log.info(
        "✅ knowledge.eval — memory run complete · remembered=%d · recalled_for=%d/%d · "
        "judged=%s · pass=%d · set=%s",
        summary["remembered_turns"],
        summary["recalled_for"],
        total,
        judged,
        passing_recall,
        set_id,
    )
    return summary


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _run_one_question(
    service: Any,
    q: dict[str, Any],
    *,
    modes: list[str],
    filters: dict[str, Any],
    top_k: int | None,
    min_score: float | None,
    model: Any | None = None,
    model_id: str = "",
    judge: bool = False,
    sink: Any | None = None,
    run_id: str = "",
) -> QuestionResult:
    """One knowledge question → N-leg fan-out (answer per leg) → optional LLM judge → one row.

    ``answer_legs`` already ledgers each leg's answer as its own Graph Run. When ``judge`` is on,
    the leg's answer is graded by the LLM judge (vs the ideal ``expected_answer``) inside a
    per-question ``knowledge_eval_judge`` run, so the verdict's grading call shows in Graph Runs
    too. With ``judge`` off, legs carry the answer but no mark (answers-only)."""
    from hirocli.services.knowledge.eval_judge import judge_answer

    results = await service.answer_legs(
        q["question"],
        modes=modes,
        top_k=top_k,
        min_score=min_score,
        filters=filters,
        rewrite=True,
    )
    gold = q.get("expected_answer", "")
    must_not = q.get("must_not_contain") or []
    is_control = str(q.get("expected_kind") or "") == "abstain"
    legs: dict[str, LegResult] = {}
    marks: dict[str, str] = {}

    # Optional judge: one run per question holding a judge node per leg (priced in Graph Runs).
    judging = judge and model is not None and sink is not None
    run_token = None
    if judging:
        from hirocli.runtime.agent_graph.ledger import RunAccumulator, current_run

        acc = RunAccumulator(
            sink=sink,
            run_id=f"knowledge_eval_judge-{run_id}-{slug_group_part(str(q.get('id') or ''))}",
            inbound_id=str(q.get("id") or ""),
        )
        run_token = current_run.set(acc)
    try:
        for mode in modes:  # preserve requested column order
            res = results.get(mode)
            if res is None:
                continue
            answer = res.answer or ""
            mark, reason = "", ""
            if judging:
                verdict = await judge_answer(
                    model,
                    model_id,
                    question=q["question"],
                    answer=answer,
                    expected_answer=gold,
                    must_not_contain=must_not,
                    is_negative_control=is_control,
                    sink=sink,
                )
                mark, reason = verdict.mark, verdict.reason
            marks[mode] = mark
            legs[mode] = LegResult(
                mode=mode,
                mark=mark,
                elapsed_ms=int(res.elapsed_ms or 0),
                answer=answer,
                run_id=getattr(res, "run_id", None),
                reason=reason,
            )
        if judging:
            sink.write_run_row(
                acc,
                status="completed",
                decision_kind="completed",
                decision_detail="knowledge_eval_judge",
                input_preview=f"q: {q['question'][:160]}",
                output_preview=" ".join(f"{m}:{mk or '—'}" for m, mk in marks.items()),
            )
    finally:
        if run_token is not None:
            from hirocli.runtime.agent_graph.ledger import current_run as _cr

            sink.evict_run(acc.run_id)
            _cr.reset(run_token)
    return QuestionResult(
        id=q["id"],
        category=q.get("category", ""),
        subcategory=q.get("subcategory", ""),
        question=q["question"],
        requires_graph=bool(q.get("requires_graph")),
        legs=legs,
        delta=_best_graph_delta_marks(marks),
        track="knowledge",
        gold=gold,
        must_not_contain=must_not,
    )


def _best_graph_delta_marks(marks: dict[str, str]) -> str:
    """Signed rank delta of the BEST graph leg's mark vs flat's — the table's Δ column.

    "+N" when a graph leg beats flat, "-N" when it trails, "0" on tie / when flat or all
    graph legs are absent / unjudged (empty marks rank 0, so an unjudged run shows Δ 0)."""
    flat = marks.get("flat")
    graph_marks = [mk for m, mk in marks.items() if m != "flat"]
    if flat is None or not graph_marks:
        return "0"
    best_graph = max(MARK_RANK.get(mk, 0) for mk in graph_marks)
    diff = best_graph - MARK_RANK.get(flat, 0)
    if diff > 0:
        return f"+{diff}"
    if diff < 0:
        return str(diff)
    return "0"


def category_breakdown(
    rows: list[QuestionResult], modes: list[str]
) -> dict[str, dict[str, Any]]:
    """Per-category × N-leg passing counts — the per-category results table.

    Shape: ``{category: {"total": int, "pass": {leg: count}}}``. Pure so tests can
    reuse it. ``category`` empty → ``"uncategorized"``."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        cat = r.category or "uncategorized"
        bucket = out.setdefault(cat, {"total": 0, "pass": {m: 0 for m in modes}})
        bucket["total"] += 1
        for mode in modes:
            leg = r.legs.get(mode)
            if leg is not None and leg.mark in _PASSING_MARKS:
                bucket["pass"][mode] += 1
    return out


def category_breakdown_rows(
    rows: list[dict[str, Any]], modes: list[str]
) -> dict[str, dict[str, Any]]:
    """Per-category × leg passing counts over **dict** rows (the memory track's payloads).

    Mirrors :func:`category_breakdown` but reads ``row['legs'][mode]['mark']`` from the dict
    shape the memory runner emits. ``category`` empty → ``"uncategorized"``."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        cat = str(r.get("category") or "") or "uncategorized"
        bucket = out.setdefault(cat, {"total": 0, "pass": {m: 0 for m in modes}})
        bucket["total"] += 1
        legs = r.get("legs") or {}
        for mode in modes:
            leg = legs.get(mode) or {}
            if leg.get("mark") in _PASSING_MARKS:
                bucket["pass"][mode] += 1
    return out


def _summarize(
    run_id: str,
    rows: list[QuestionResult],
    started_at: float,
    modes: list[str],
    *,
    judged: bool = True,
) -> EvalSummary:
    """Compute the gate + per-leg aggregate counts the UI/CLI surfaces."""

    def _passing(subset: list[QuestionResult]) -> dict[str, int]:
        return {
            m: sum(
                1
                for r in subset
                if (leg := r.legs.get(m)) is not None and leg.mark in _PASSING_MARKS
            )
            for m in modes
        }

    requires = [r for r in rows if r.requires_graph]
    passing = _passing(rows)
    req_passing = _passing(requires)
    # Gate: a graph leg must MEASURABLY beat flat on the requires_graph subset. Needs the
    # judge on (marks exist) AND flat + a graph leg; otherwise undefined → "n/a".
    graph_modes = [m for m in modes if m != "flat"]
    if judged and "flat" in modes and graph_modes:
        best_graph_req = max(req_passing[m] for m in graph_modes)
        gate = "proceed" if best_graph_req > req_passing["flat"] else "pivot"
    else:
        gate = "n/a"
    return EvalSummary(
        run_id=run_id,
        total_questions=len(rows),
        modes=list(modes),
        passing=passing,
        requires_graph_total=len(requires),
        requires_graph_passing=req_passing,
        gate=gate,
        judged=judged,
        elapsed_ms=int((time.perf_counter() - started_at) * 1000),
        questions=list(rows),
        by_category=category_breakdown(rows, modes),
    )


def _publish(
    bus: Any, workspace_path: Path, event_type: str, payload: dict[str, Any]
) -> None:
    """Wrap publish in a try/except so a bus glitch never aborts the run.

    The event bus already wraps handlers in try/except; this guards the
    publish path itself (e.g. if the loop is detached during shutdown)."""
    try:
        bus.publish(
            DomainEvent(type=event_type, workspace_path=workspace_path, payload=dict(payload))
        )
    except Exception:
        log.warning("⚠️ knowledge.eval — event publish failed", event_type=event_type, exc_info=True)


def _preview(text: str, limit: int) -> str:
    s = " ".join((text or "").split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


async def collect_synthetic_doc_ids(service: Any) -> list[str]:
    """Return doc_ids of every workspace document carrying the eval tag.

    Used by the ``ingest_synthetic=False, build_graph=True`` path — graph-build
    over docs already in the workspace without re-ingesting. Also handy from the
    admin route so the UI can show "no synthetic docs found, ingest first" hints.
    """
    docs_result = await service.list_documents(tag=EVAL_SYNTHETIC_TAG, limit=500)
    return [d.id for d in docs_result.documents]


async def collect_eval_doc_ids(service: Any) -> list[str]:
    """Return doc_ids of every KNOWLEDGE-track eval document (tag ``_l3_eval_synthetic``).

    The memory track no longer writes knowledge documents (its data lives in the
    ``eval_mem_{set}`` graph drawer, cleared by group — not by document), so the knowledge
    eval footprint is exactly the synthetic-tagged docs."""
    docs_result = await service.list_documents(tag=EVAL_SYNTHETIC_TAG, limit=500)
    return [doc.id for doc in docs_result.documents]


async def clear_eval_data(service: Any) -> int:
    """Delete the KNOWLEDGE-track eval data (synthetic corpus) — catalog rows, Qdrant
    chunks, and graph episodes — and return the document count removed.

    Document-scoped over the eval-tagged docs: ``service.delete_document`` purges all three
    stores per document (catalog + Qdrant + graph episodes). Idempotent: a workspace with no
    eval docs removes 0. (The MEMORY track clears separately by graph group — ``clear_all`` /
    ``clear_group("eval_mem_{set}")``.)
    """
    doc_ids = await collect_eval_doc_ids(service)
    if not doc_ids:
        log.info("🧹 knowledge.eval — no eval documents to clear")
        return 0
    removed = 0
    for doc_id in doc_ids:
        try:
            result = await service.delete_document(doc_id)
        except Exception:
            # External stores (catalog/Qdrant/Kuzu) — log + continue so one stuck doc
            # doesn't strand the rest of the eval wipe.
            log.warning(
                "⚠️ knowledge.eval — failed to delete eval doc · doc_id=%s", doc_id, exc_info=True
            )
            continue
        if result.get("deleted"):
            removed += 1
    log.info("🧹 knowledge.eval — cleared eval data · documents=%d/%d", removed, len(doc_ids))
    return removed


__all__ = [
    "ADAM_CORPUS_FILE",
    "ADAM_QUESTIONS_FILE",
    "ALL_EVAL_MODES",
    "DEFAULT_CORPUS_DIR",
    "DEFAULT_EVAL_FOLDER",
    "DEFAULT_EVAL_MODES",
    "DEFAULT_MEMORY_EVAL_SET",
    "DEFAULT_QUESTIONS_FILE",
    "EVAL_SYNTHETIC_TAG",
    "MEMORY_EVAL_USER_ID",
    "discover_corpuses",
    "EvalSummary",
    "LegResult",
    "QuestionResult",
    "category_breakdown",
    "clear_eval_data",
    "collect_eval_doc_ids",
    "collect_synthetic_doc_ids",
    "ingest_synthetic_corpus_via_service",
    "load_adam_questions",
    "load_questions",
    "normalize_modes",
    "run_eval",
    "run_memory_eval",
]
