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
from hirocli.runtime.agent_graph.tracing import traced_run
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
    KNOWLEDGE_GRAPH_INGEST_COMPLETED,
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
#
# Legacy flat tag — matched only the single bundled l3_synthetic corpus. Kept for the
# legacy CLI tool path (knowledge_eval.py). The admin route uses the per-corpus tag below.
EVAL_SYNTHETIC_TAG = "_l3_eval_synthetic"

# Per-corpus knowledge-eval tag — the LIVE convention. The admin route tags every ingested
# eval doc with ``_eval_kb_{corpus_id}`` so retrieval AND clear scope to one corpus. Minted
# here (single source) so ingest + clear can't drift onto different tags (the bug that
# stranded orphan eval vectors when the manual clear keyed off the stale flat tag).
EVAL_KB_TAG_PREFIX = "_eval_kb_"


def eval_kb_tag(corpus_id: str) -> str:
    """The per-corpus knowledge-eval document tag (``_eval_kb_{corpus_id}``)."""
    return f"{EVAL_KB_TAG_PREFIX}{corpus_id}"


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
    recalled: tuple[Any, ...] = ()  # memory: the recalled facts (structured rows for the table)
    cost_usd: float = 0.0  # this leg's folded LLM+reranker cost (read from its run; 0 if unknown)

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
            "legs": {mode: leg.to_payload() for mode, leg in self.legs.items()},
            "delta": self.delta,
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
    # difficulty → {total, pass: {leg: count}} — same shape, bucketed by authored difficulty.
    by_difficulty: dict[str, dict[str, Any]] = field(default_factory=dict)
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
            "questions_cost_usd": self.questions_cost_usd,
            "ingest_cost_usd": self.ingest_cost_usd,
            "total_cost_usd": self.questions_cost_usd + self.ingest_cost_usd,
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
                # Authored difficulty (medium/hard/very_hard). Optional — corpora without it
                # fall into the "unspecified" bucket in the by_difficulty report. Reporting-only.
                "difficulty": str(row.get("difficulty") or "").strip().lower(),
                "question": qtext,
                "expected_fragments": [str(f) for f in expected],
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
    # Always create the sink — even judge-off — so per-leg cost can be read back from the
    # ledger (cost is NOT judge-dependent). Judge rows are only written when judging.
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
    # One LangSmith root span for the whole run so each question's answer legs + judge
    # nest under it instead of scattering as independent roots. run_id = uuid5(rid) ⇒ the
    # admin "open in LangSmith" link (langsmith_url_for_run) resolves it. No-op when off.
    with traced_run(
        "knowledge_eval",
        ledger_run_id=rid,
        tags=["eval", "knowledge", f"judge:{judged}"],
        metadata={"total_questions": total, "modes": run_modes, "filters": eval_filters},
    ):
        try:
            for index, q in enumerate(questions):
                # Per-question child span — answer legs (each its own knowledge_answer run)
                # and the judge call attach here, so a question reads as one subtree.
                with traced_run(
                    "eval_question",
                    tags=["eval", "knowledge", str(q.get("category") or "")],
                    metadata={
                        "id": q.get("id"),
                        "requires_graph": bool(q.get("requires_graph")),
                    },
                    inputs={"question": q.get("question", "")},
                ):
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
    log.info(
        "✅ knowledge.eval — run complete · gate=%s · judged=%s · cost=$%.4f (Q; ingest deferred) · ms=%d",
        summary.gate,
        judged,
        summary.questions_cost_usd,
        summary.elapsed_ms,
    )
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
            # Number each turn's LangSmith ingest tree so they read graph_ingest_1, _2, … under
            # the ingestion root (instead of N identical "graph_ingest" siblings).
            trace_label=f"graph_ingest_{index}",
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
    answer_system_prompt: str = "",
) -> dict[str, Any]:
    """One memory question, all in ONE Graph Run: **recall** (graph search) → **answer**
    (grounded only in the recalled facts) → optional **judge** (vs the ideal answer).

    The run holds a ``memory_recall`` node (graph-search spans), an ``eval_answer`` node, and an
    ``eval_judge`` node — all priced. Returns the unified row (``legs={'recall': {...}}`` with the
    model answer + verdict mark + recalled facts, plus ``gold``)."""
    from hirocli.runtime.agent_graph.ledger import RunAccumulator, current_entry, current_run
    from hirocli.services.knowledge.eval_judge import answer_from_context, judge_answer
    from hirocli.services.knowledge.ledger_runner import preview_answer, preview_query

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
    recalled_rows: list[dict[str, Any]] = []
    answer, mark, reason = "", "", ""
    # Judge-reported: did the recalled context contain what was needed to answer? Defaults True
    # (judge off / not asked) so it never falsely flags a recall miss when unjudged.
    recall_sufficient = True
    cost_usd = 0.0
    t0 = time.perf_counter()
    try:
        # 1) recall (graph search) — its own LangSmith ``recall`` span so the per-lane rerank(s)
        # + query-embedding group under it; ledgered as a memory_recall node when a sink present.
        with traced_run("recall", inputs={"question": q["question"]}) as _recall_rt:
            if sink is not None:
                # captures={"usage","decision"} is REQUIRED: without it to_row() blanks the recall
                # node's usage block (model/tokens), so its folded reranker/search cost was lost and
                # the per-question total under-counted (showed $0 when recall was the only priced
                # leg). Mirrors eval_answer/eval_judge (_ledger_llm_node) and the ingest nodes.
                entry = sink.open_entry(
                    "memory_recall", {}, None, captures=frozenset({"usage", "decision"})
                )
                entry_token = current_entry.set(entry)
                try:
                    hits = await memory.search(
                        q["question"], user_id=user_id, character_id=character_id
                    )
                    facts = [
                        str(h.get("memory") or "")
                        for h in hits
                        if str(h.get("memory") or "").strip()
                    ]
                    entry.input_preview = preview_query(q["question"])
                    entry.output_preview = preview_answer(" | ".join(facts) or "(nothing recalled)")
                finally:
                    entry.finish("ok")
                    sink.write_rows(entry.rows(include_parent=True))
                    current_entry.reset(entry_token)
            else:
                hits = await memory.search(
                    q["question"], user_id=user_id, character_id=character_id
                )
                facts = [
                    str(h.get("memory") or "") for h in hits if str(h.get("memory") or "").strip()
                ]
            # Structured recalled rows (kind + metadata) feed BOTH the answer/judge prompts and the
            # results fact table; the plain ``facts`` strings remain for previews/fallbacks.
            recalled_rows = [h for h in hits if str(h.get("memory") or "").strip()]
            if _recall_rt is not None:
                _recall_rt.outputs = {
                    "recalled": len(recalled_rows),
                    "facts": sum(1 for h in recalled_rows if (h.get("kind") or "fact") == "fact"),
                    "entities": sum(1 for h in recalled_rows if h.get("kind") == "entity"),
                    "episodes": sum(1 for h in recalled_rows if h.get("kind") == "episode"),
                }
        # 2) answer — grounded ONLY in the recalled context (structured: facts/entities/episodes).
        if model is not None:
            answer = await answer_from_context(
                model,
                model_id,
                question=q["question"],
                context=recalled_rows,
                sink=sink,
                # Editable graph.eval.memory_answer_prompt (blank → relaxed default in eval_judge).
                system_prompt=answer_system_prompt,
            )
        # 3) judge — vs the ideal answer (optional step). Gets the SAME recalled context so it can
        # set recall_sufficient (recall-miss vs answering-miss), not just grade vs the ideal.
        if judge and model is not None:
            verdict = await judge_answer(
                model,
                model_id,
                question=q["question"],
                answer=answer,
                expected_answer=gold,
                context=recalled_rows,
                is_negative_control=is_control,
                sink=sink,
            )
            mark, reason = verdict.mark, verdict.reason
            recall_sufficient = verdict.recall_sufficient
        if sink is not None and acc is not None:
            sink.write_run_row(
                acc,
                status="completed",
                decision_kind="completed",
                decision_detail="memory_eval_question",
                input_preview=f"q: {q['question'][:160]}",
                output_preview=(answer or " | ".join(facts))[:200],
            )
            # The per-question run accumulator folds recall + answer + judge node costs →
            # the whole question's LLM+reranker cost (read in-memory before evict).
            cost_usd = float(getattr(acc, "cost_usd", 0.0) or 0.0)
    finally:
        if run_token is not None and acc is not None:
            sink.evict_run(acc.run_id)
            current_run.reset(run_token)

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "id": q["id"],
        "category": q.get("category", ""),
        "subcategory": q.get("subcategory", ""),
        "difficulty": q.get("difficulty", ""),
        "question": q["question"],
        "requires_graph": bool(q.get("requires_graph")),
        "track": "memory",
        "gold": gold,
        "delta": "0",
        "cost_usd": cost_usd,
        "legs": {
            "recall": {
                "mode": "recall",
                "mark": mark,
                "reason": reason,
                "elapsed_ms": elapsed_ms,
                "answer": answer,
                "answer_preview": _preview(answer, 200),
                "run_id": (acc.run_id if acc is not None else None),
                "recalled": recalled_rows,
                "recall_sufficient": recall_sufficient,
                "cost_usd": cost_usd,
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
    # Editable memory-eval answer prompt (graph.eval.memory_answer_prompt); blank → relaxed default.
    from hirocli.domain.preferences import load_preferences

    memory_answer_prompt = load_preferences(workspace_path).graph.eval.memory_answer_prompt
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
    # TWO sibling LangSmith roots per corpus (no shared umbrella), so the build and the question
    # batch read as separate trees: ``memory_eval_{set}_ingestion`` (the remember leg) and
    # ``memory_eval_{set}_questions`` (the eval_question group). No-op when tracing is off.
    try:
        remembered = 0
        ingest_cost_usd = 0.0
        # The remember phase's ingest Graph Run id — surfaced to the panel so it can open the
        # ingest pipeline trace. Empty on a question-subset re-run (remember=False = no ingest).
        ingest_run_id = ""
        if remember:
            eps = episodes if episodes is not None else load_episodes_file(
                corpus_path or ADAM_CORPUS_FILE
            )
            # Rebuild = clean slate. Wipe this eval set's graph drawer BEFORE re-remembering
            # so the run rebuilds from scratch. Re-ingesting the same turns over an existing
            # graph let Graphiti dedup/invalidate against stale state — a prior run's facts
            # contaminated the next (observed: spurious edges + bad supersessions on re-run).
            # Gated on `remember`: a question-subset re-run (remember=False) recalls the
            # existing drawer untouched. Eval-scoped facade ⇒ clear_all targets only the
            # eval_mem_{set} drawer.
            cleared = await memory.clear_all(user_id=eval_user_id, character_id=character_id)
            if cleared:
                log.info(
                    "🧹 knowledge.eval — memory rebuild · cleared %d prior fact(s) · set=%s",
                    cleared,
                    set_id,
                )
            # Open ONE parent run so every turn's Graphiti extraction nests under it (priced
            # sub-rows fold into the aggregate) — the memory "ingest" Graph Run.
            ledger_run_id = f"memory_eval-{slug_group_part(set_id)}-{rid}"
            ingest_run_id = ledger_run_id
            # Root 1 — INGESTION: its own LangSmith tree for the "remember" leg; every turn's
            # graph_ingest_{n}/add_episode span nests here. ledger_run_id aligns the span id with
            # the ingest Graph Run row (so "open in LangSmith" links from it).
            with traced_run(
                f"memory_eval_{set_id}_ingestion",
                ledger_run_id=ledger_run_id,
                tags=["eval", "memory", "ingest", f"set:{set_id}"],
                metadata={"set": set_id, "episode_count": len(eps)},
            ):
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
                    # Ingest (graph build) cost — the remember run's folded LLM+reranker cost.
                    ingest_cost_usd = float(getattr(accumulator, "cost_usd", 0.0) or 0.0)
                    # Stream the ingest cost the moment the remember phase ends — emitted as a
                    # setup_progress line so the panel surfaces graph-build cost LIVE, instead of
                    # only when the terminal `completed` summary lands at run end. The remember
                    # phase is the priciest part and runs before any question row exists, so
                    # without this the cost UI showed nothing during ingestion.
                    _publish(
                        bus,
                        workspace_path,
                        KNOWLEDGE_EVAL_SETUP_PROGRESS,
                        {
                            "run_id": rid,
                            "phase": "remember_done",
                            "episode_count": len(eps),
                            "ingest_cost_usd": ingest_cost_usd,
                            # Lets the panel open the ingest pipeline trace for this remember run.
                            "ingest_run_id": ingest_run_id,
                        },
                    )
                    # Pair the per-turn graph ingest_progress events (emitted by the memory
                    # facade's graph event_sink) with ONE completion, scoped to this eval's
                    # group. Without it the Graph tab's "ingesting chunk N/M…" status had
                    # nothing to clear on the memory track and stuck until a manual refresh
                    # (only the knowledge routes emitted ingest_completed). One event per
                    # remember phase (not per turn) keeps the Graph tab's reconcile cheap.
                    _publish(
                        bus,
                        workspace_path,
                        KNOWLEDGE_GRAPH_INGEST_COMPLETED,
                        {"group_id": eval_memory_group_id(set_id)},
                    )
                finally:
                    sink.evict_run(ledger_run_id)
                    current_run.reset(token)
        # Root 2 — QUESTIONS: its own LangSmith tree; each question nests under it as an
        # ``eval_question`` span (recall → answer → judge).
        with traced_run(
            f"memory_eval_{set_id}_questions",
            ledger_run_id=rid,
            tags=["eval", "memory", "questions", f"set:{set_id}", f"judge:{judged}"],
            metadata={"total_questions": total, "set": set_id},
        ):
            for index, q in enumerate(questions):
                # Align the eval_question span id with THIS question's per-question Graph Run row
                # (same formula _memory_question uses) so "open in LangSmith" links from the row.
                q_run_id = (
                    f"memory_eval_q-{slug_group_part(set_id)}-{rid}-"
                    f"{slug_group_part(str(q.get('id') or ''))}"
                )
                with traced_run(
                    "eval_question",
                    ledger_run_id=q_run_id,
                    tags=["eval", "memory", str(q.get("category") or "")],
                    metadata={"id": q.get("id")},
                    inputs={"question": q.get("question", "")},
                ):
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
                        answer_system_prompt=memory_answer_prompt,
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

    # Shared aggregate shape (also used by the persisted-results merged read), then
    # augment with this run's ingest-specific fields the merged snapshot can't carry:
    # remembered_turns, the real wall-clock elapsed, and the remember/graph-build cost.
    summary = summarize_memory_rows(rows, run_id=rid, judged=judged)
    summary["remembered_turns"] = remembered
    summary["elapsed_ms"] = int((time.perf_counter() - started_at) * 1000)
    # Cost (LLM + reranker; embeddings unpriced). Ingest = the remember/graph-build run;
    # questions = sum of per-question recall+answer+judge runs.
    summary["ingest_cost_usd"] = ingest_cost_usd
    summary["total_cost_usd"] = ingest_cost_usd + summary["questions_cost_usd"]
    # Carry the ingest Graph Run id so the panel's "Ingest pipeline" button can open its trace
    # (only set when this run actually remembered; a subset re-run leaves it empty → None).
    summary["ingest_run_id"] = ingest_run_id or None
    passing_recall = summary["passing"]["recall"]
    _publish(bus, workspace_path, KNOWLEDGE_EVAL_COMPLETED, summary)
    log.info(
        "✅ knowledge.eval — memory run complete · remembered=%d · recalled_for=%d/%d · "
        "judged=%s · pass=%d · cost=$%.4f (ingest $%.4f + Q $%.4f) · set=%s",
        summary["remembered_turns"],
        summary["recalled_for"],
        total,
        judged,
        passing_recall,
        summary["total_cost_usd"],
        summary["ingest_cost_usd"],
        summary["questions_cost_usd"],
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
    is_control = str(q.get("expected_kind") or "") == "abstain"
    # Per-leg cost — each leg's answer already ran as its own (now-written) Graph Run; read the
    # folded cost back by run_id (LLM + reranker; embeddings unpriced). Judge cost added below.
    leg_run_ids = {getattr(r, "run_id", None) for r in results.values() if getattr(r, "run_id", None)}
    leg_costs = sink.read_run_costs(leg_run_ids) if sink is not None else {}
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
                cost_usd=float(leg_costs.get(str(getattr(res, "run_id", "") or ""), 0.0)),
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
    # Whole-question cost = sum of leg answer runs + the judge run (when judged).
    judge_cost = float(getattr(acc, "cost_usd", 0.0) or 0.0) if judging else 0.0
    question_cost = sum(leg.cost_usd for leg in legs.values()) + judge_cost
    return QuestionResult(
        id=q["id"],
        category=q.get("category", ""),
        subcategory=q.get("subcategory", ""),
        difficulty=q.get("difficulty", ""),
        question=q["question"],
        requires_graph=bool(q.get("requires_graph")),
        legs=legs,
        delta=_best_graph_delta_marks(marks),
        track="knowledge",
        gold=gold,
        cost_usd=question_cost,
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


def field_breakdown(
    rows: list[QuestionResult],
    modes: list[str],
    *,
    field: str = "category",
    fallback: str = "uncategorized",
) -> dict[str, dict[str, Any]]:
    """Per-``field`` × N-leg passing counts — drives the per-category / per-difficulty tables.

    Shape: ``{key: {"total": int, "pass": {leg: count}}}``, keyed by the named
    ``QuestionResult`` attribute (``category`` or ``difficulty``). Pure so tests can
    reuse it. Empty attribute → ``fallback``."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = getattr(r, field, "") or fallback
        bucket = out.setdefault(key, {"total": 0, "pass": {m: 0 for m in modes}})
        bucket["total"] += 1
        for mode in modes:
            leg = r.legs.get(mode)
            if leg is not None and leg.mark in _PASSING_MARKS:
                bucket["pass"][mode] += 1
    return out


def field_breakdown_rows(
    rows: list[dict[str, Any]],
    modes: list[str],
    *,
    field: str = "category",
    fallback: str = "uncategorized",
) -> dict[str, dict[str, Any]]:
    """Per-``field`` × leg passing counts over **dict** rows (the memory track's payloads).

    Mirrors :func:`field_breakdown` but reads ``row[field]`` and ``row['legs'][mode]['mark']``
    from the dict shape the memory runner emits. Empty value → ``fallback``."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = str(r.get(field) or "") or fallback
        bucket = out.setdefault(key, {"total": 0, "pass": {m: 0 for m in modes}})
        bucket["total"] += 1
        legs = r.get("legs") or {}
        for mode in modes:
            leg = legs.get(mode) or {}
            if leg.get("mark") in _PASSING_MARKS:
                bucket["pass"][mode] += 1
    return out


def _memory_recall_leg(row: dict[str, Any]) -> dict[str, Any]:
    """The single ``recall`` leg of a memory-track question row (or ``{}``)."""
    return (row.get("legs") or {}).get("recall") or {}


def summarize_memory_rows(
    rows: list[dict[str, Any]],
    *,
    run_id: str = "merged",
    judged: bool | None = None,
) -> dict[str, Any]:
    """Aggregate a set of memory-track question rows into the summary payload.

    The single source of truth for the memory summary shape — used both by the
    live runner (one run's rows) and by the persisted-results read path (the
    merged per-corpus snapshot, where ``run_id``/ingest cost aren't meaningful).
    ``judged`` is inferred from the presence of judge marks when not given."""
    total = len(rows)
    if judged is None:
        # Merged read can't know the original judge flag → infer from the marks.
        judged = any(_memory_recall_leg(r).get("mark") for r in rows)
    passing_recall = sum(
        1 for r in rows if _memory_recall_leg(r).get("mark") in _PASSING_MARKS
    )
    questions_cost_usd = sum(float(r.get("cost_usd") or 0.0) for r in rows)
    return {
        "run_id": run_id,
        "track": "memory",
        "total_questions": total,
        "modes": ["recall"],
        "judged": judged,
        "recalled_for": sum(1 for r in rows if _memory_recall_leg(r).get("recalled")),
        # Judge pass-count for the single recall leg (0 when the judge was off).
        "passing": {"recall": passing_recall},
        # No flat/graph legs → the PROCEED/PIVOT gate is undefined for the memory track.
        "gate": "n/a",
        "by_category": field_breakdown_rows(rows, ["recall"], field="category"),
        "by_difficulty": field_breakdown_rows(
            rows, ["recall"], field="difficulty", fallback="unspecified"
        ),
        # Sum of per-question recall elapsed — the merged snapshot has no single
        # wall-clock; the live runner overrides this with its real run duration.
        "elapsed_ms": sum(int(_memory_recall_leg(r).get("elapsed_ms") or 0) for r in rows),
        # Merged snapshot spans many runs → no single ingest cost; questions only.
        "ingest_cost_usd": 0.0,
        "questions_cost_usd": questions_cost_usd,
        "total_cost_usd": questions_cost_usd,
    }


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
        by_category=field_breakdown(rows, modes, field="category"),
        by_difficulty=field_breakdown(rows, modes, field="difficulty", fallback="unspecified"),
        # LLM + reranker cost summed across questions (knowledge ingest cost deferred → 0).
        questions_cost_usd=sum(float(r.cost_usd or 0.0) for r in rows),
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


async def collect_eval_doc_ids(service: Any, corpus_id: str) -> list[str]:
    """Return doc_ids of one KNOWLEDGE-track eval corpus (tag ``_eval_kb_{corpus_id}``).

    The memory track no longer writes knowledge documents (its data lives in the
    ``eval_mem_{set}`` graph drawer, cleared by group — not by document), so the knowledge
    eval footprint is exactly this corpus's tagged docs."""
    docs_result = await service.list_documents(tag=eval_kb_tag(corpus_id), limit=500)
    return [doc.id for doc in docs_result.documents]


async def clear_eval_data(service: Any, corpus_id: str) -> int:
    """Delete one KNOWLEDGE-track eval corpus — catalog rows, Qdrant chunks, and graph
    episodes — and return the document count removed.

    Scopes to the LIVE per-corpus tag (``_eval_kb_{corpus_id}``): ``service.delete_document``
    purges all three stores per document (catalog + Qdrant + graph episodes). Idempotent: a
    corpus with no eval docs removes 0. (The MEMORY track clears separately by graph group —
    ``clear_all`` / ``clear_group("eval_mem_{set}")``.)
    """
    doc_ids = await collect_eval_doc_ids(service, corpus_id)
    if not doc_ids:
        log.info("🧹 knowledge.eval — no eval documents to clear · corpus=%s", corpus_id)
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
    log.info(
        "🧹 knowledge.eval — cleared eval data · corpus=%s · documents=%d/%d",
        corpus_id,
        removed,
        len(doc_ids),
    )
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
    "EVAL_KB_TAG_PREFIX",
    "eval_kb_tag",
    "MEMORY_EVAL_USER_ID",
    "discover_corpuses",
    "EvalSummary",
    "LegResult",
    "QuestionResult",
    "field_breakdown",
    "field_breakdown_rows",
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
