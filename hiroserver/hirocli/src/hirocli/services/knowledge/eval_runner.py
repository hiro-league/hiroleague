"""L3 eval runner — in-process orchestrator that publishes per-question events.

Mirrors ``eval/l3_synthetic_eval.py``'s logic (load corpus, ingest, build graph,
run each question via compare, score, summarize) but as an **awaitable function
that publishes Domain Events as it goes** — so the admin Eval Batch UI can
update the table live via the existing ``/knowledge/events`` SSE stream
(Phase 5c).

The standalone CLI harness still works for terminal use (it imports the shared
:mod:`eval_scoring` for its own scoring path). The runner here is the in-server
path; both arrive at the same numbers because they share the scorer.

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
    score_answer,
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
DEFAULT_QUESTIONS_FILE = _REPO_ROOT / "eval" / "l3_questions.yaml"


# Tag auto-applied to ingested eval docs so flat/graph retrieval can be scoped
# to ONLY the synthetic corpus (so the eval comparison stays fair even when the
# workspace has unrelated knowledge docs already ingested). See plan §5f.
EVAL_SYNTHETIC_TAG = "_l3_eval_synthetic"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


# The selectable eval legs (retrieval modes). "flat" = no graph (Qdrant hybrid);
# "graphiti" = graph facts + their episode chunks by-id (no query hybrid); "mix" =
# graph facts focus the Qdrant hybrid (fused). Any non-empty subset is runnable,
# including a single leg. Order here is the canonical column order in the UI.
ALL_EVAL_MODES: tuple[str, ...] = ("flat", "graphiti", "mix")
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
    """One leg's scored outcome for a single question."""

    mode: str          # "flat" | "graphiti" | "mix"
    mark: str          # one of MARK_*
    elapsed_ms: int
    answer: str
    run_id: str | None

    def to_payload(self) -> dict[str, Any]:
        # Compact ``answer_preview`` for the live terminal line + the FULL ``answer``
        # for the expandable row; ``run_id`` for the per-leg "Open in Graph Runs" link.
        return {
            "mode": self.mode,
            "mark": self.mark,
            "elapsed_ms": self.elapsed_ms,
            "answer_preview": _preview(self.answer, 200),
            "answer": self.answer,
            "run_id": self.run_id,
        }


@dataclass(frozen=True)
class QuestionResult:
    """Per-question outcome across the selected legs."""

    id: str
    category: str
    question: str
    requires_graph: bool
    # Leg name → that leg's scored result. Keyed by the modes the run selected.
    legs: dict[str, LegResult]
    # Best graph leg (graphiti/mix) vs flat, as a signed rank delta for the table's
    # Δ column. "0" when flat wasn't run or no graph leg beat it.
    delta: str
    subcategory: str = ""
    # The scoring rubric, surfaced so the panel can show what each answer is judged
    # against (the substrings score_answer requires / forbids). Display-only.
    expected_fragments: list[str] = field(default_factory=list)
    must_not_contain: list[str] = field(default_factory=list)

    def to_payload(self, *, index: int, total: int) -> dict[str, Any]:
        """Event payload shape consumed by the Eval Batch UI.

        ``legs`` is keyed by leg name so the panel renders one column per selected
        leg (1–3). For a ≤50-question eval the full-answer bytes are negligible and
        let the panel show full answers live without a second round-trip."""
        return {
            "index": index,
            "total": total,
            "id": self.id,
            "category": self.category,
            "subcategory": self.subcategory,
            "question": self.question,
            "requires_graph": self.requires_graph,
            "legs": {mode: leg.to_payload() for mode, leg in self.legs.items()},
            "delta": self.delta,
            # Scoring rubric for this question (display-only): what answers are judged
            # against. Empty expected_fragments = negative-control (abstain is correct).
            "expected_fragments": self.expected_fragments,
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
    questions: list[QuestionResult] = field(default_factory=list)
    # category → {total, pass: {leg: count}} — the per-category × N-leg table.
    by_category: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "total_questions": self.total_questions,
            "modes": self.modes,
            "passing": self.passing,
            "requires_graph_total": self.requires_graph_total,
            "requires_graph_passing": self.requires_graph_passing,
            "gate": self.gate,
            "elapsed_ms": self.elapsed_ms,
            "by_category": self.by_category,
        }


# ---------------------------------------------------------------------------
# Public surfaces
# ---------------------------------------------------------------------------


def load_questions(path: Path | None = None) -> list[dict[str, Any]]:
    """Load + validate the eval questions YAML.

    Each row must have ``id``, ``question``, ``expected_fragments`` (list, may
    be empty for negative-control rows). Extra keys (category, requires_graph,
    notes) are passed through but optional."""
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
        # ``expected_kind: abstain`` is shorthand for the negative-control (empty
        # expected_fragments) — abstain is the correct outcome, a confident answer fails.
        expected_kind = str(row.get("expected_kind") or "").strip().lower()
        expected = row.get("expected_fragments")
        if expected_kind == "abstain":
            expected = expected if isinstance(expected, list) else []
        elif expected is None or not isinstance(expected, list):
            raise ValueError(
                f"{target}: row {i} ({qid}): expected_fragments must be a list "
                f"(use [] or expected_kind: abstain for negative-control rows)"
            )
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
            }
        )
    return out


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

    _publish(
        bus,
        workspace_path,
        KNOWLEDGE_EVAL_STARTED,
        {
            "run_id": rid,
            "total_questions": total,
            "filters": eval_filters,
            # Selected legs — the UI needs these up front to render the right
            # columns before the first question row arrives.
            "modes": run_modes,
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

    summary = _summarize(rid, rows, started_at, run_modes)
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
# Adam JSONL episode corpus — the temporal-aware eval (Graphiti pivot)
# ---------------------------------------------------------------------------

ADAM_CORPUS_FILE = _REPO_ROOT / "eval" / "adam_year.episodes.jsonl"
ADAM_QUESTIONS_FILE = _REPO_ROOT / "eval" / "adam_questions.yaml"
ADAM_EVAL_TAG = "_adam_eval"
# Stable namespace: episode id → the uuid used as BOTH the Qdrant point_id AND the
# Graphiti episode uuid, so a graph fact's ``episodes`` joins straight to the passage.
_ADAM_NS = uuid.uuid5(uuid.NAMESPACE_URL, "hiro.eval.adam")


def adam_point_id(episode_id: str) -> str:
    """Deterministic uuid for an episode id (Qdrant requires uuid/int ids)."""
    return str(uuid.uuid5(_ADAM_NS, episode_id))


def load_adam_questions(path: Path | None = None) -> list[dict[str, Any]]:
    """Load the Adam question bank (same validation as ``load_questions``)."""
    return load_questions(path or ADAM_QUESTIONS_FILE)


async def ingest_adam_corpus_via_service(
    service: Any,
    workspace_path: Path,
    *,
    corpus_path: Path | None = None,
    tag: str = ADAM_EVAL_TAG,
    run_id: str | None = None,
    reset_first: bool = True,
) -> int:
    """Ingest the Adam JSONL episode corpus into BOTH Qdrant and the Graphiti graph.

    Per episode: derive a shared uuid (``adam_point_id``) used as the Qdrant
    point_id **and** the Graphiti episode uuid. Qdrant gets one tagged point per
    episode (flat/mix passages); Graphiti gets the episodes sequentially in
    chronological order (temporal supersession). Requires a configured extraction
    model for the graph build.

    Emits a ``setup_progress`` event **per episode** for both the Qdrant write
    and the (slow, LLM-bound) graph extraction, so the admin terminal shows live
    progress instead of freezing for minutes on the coarse two-phase view."""
    from dataclasses import replace

    from hirocli.domain.preferences import load_preferences
    from hirocli.runtime.agent_graph.ledger import LedgerSink
    from hirocli.services.knowledge.constants import KNOWLEDGE_GRAPH_INGEST_PROGRESS
    from hirocli.services.knowledge.graph import GraphitiMemoryService
    from hirocli.services.knowledge.graph.graphiti_corpus import load_episodes_file

    episodes = load_episodes_file(corpus_path or ADAM_CORPUS_FILE)
    bus = get_domain_event_bus()
    total = len(episodes)
    _publish(
        bus,
        workspace_path,
        KNOWLEDGE_EVAL_SETUP_PROGRESS,
        {"run_id": run_id, "phase": "ingest_adam", "episode_count": total},
    )

    # The graph service is built up-front because it's needed BOTH for the optional
    # pre-run reset and the graph build below. Kuzu driver is shared/refcounted, so one
    # instance — closed once in the finally — is enough (require_backend=False so an
    # explicit eval build works even with the retrieval backend toggle off).
    prefs = load_preferences(workspace_path)
    gsvc = GraphitiMemoryService.from_preferences(prefs, workspace_path, require_backend=False)
    if gsvc is None:
        raise RuntimeError(
            "Adam eval: no extraction model configured for the Graphiti graph build. "
            "Set knowledge.graph.extraction_model or knowledge.answering.model (+ provider key)."
        )
    ledger_sink = LedgerSink(workspace_path)
    try:
        # 0) Pre-run reset — keep the eval deterministic run-to-run by deleting ONLY what a
        #    previous eval created (its Qdrant points by document_id + its graph episodes and
        #    the nodes/edges those episodes exclusively own) before re-ingesting. Targeted so
        #    other knowledge data is never touched; idempotent (a first run finds nothing).
        if reset_first:
            _publish(
                bus,
                workspace_path,
                KNOWLEDGE_EVAL_SETUP_PROGRESS,
                {"run_id": run_id, "phase": "reset_adam", "episode_count": total},
            )
            for doc_id in {ep.document_id for ep in episodes}:
                await asyncio.to_thread(service.vector_store.delete_document, doc_id)
            await gsvc.remove_episodes([adam_point_id(ep.chunk_id) for ep in episodes])

        # 1) Qdrant double-write — one tagged point per episode, point_id == shared uuid.
        graphiti_eps = []
        for ep in episodes:
            qid = adam_point_id(ep.chunk_id)
            await service.ingest_text_chunk(
                point_id=qid,
                text=ep.text,
                document_id=ep.document_id,
                title=ep.document_title,
                tags=[tag],
            )
            graphiti_eps.append(replace(ep, chunk_id=qid))
            _publish(
                bus,
                workspace_path,
                KNOWLEDGE_EVAL_SETUP_PROGRESS,
                {
                    "run_id": run_id,
                    "phase": "ingest_adam",
                    "index": len(graphiti_eps),
                    "total": total,
                    "title": ep.document_title,
                    "snippet": _preview(ep.text, 90),
                },
            )

        # 2) Graphiti graph build — sequential + chronological.
        _publish(
            bus,
            workspace_path,
            KNOWLEDGE_EVAL_SETUP_PROGRESS,
            {"run_id": run_id, "phase": "build_graph", "episode_count": len(graphiti_eps)},
        )

        # Bridge Graphiti's per-episode progress into eval terminal lines. The build
        # is the multi-minute part (one LLM extraction per episode), so this is the
        # progress the user most needs to see ticking.
        def _graph_sink(event_type: str, payload: dict[str, Any]) -> None:
            if event_type != KNOWLEDGE_GRAPH_INGEST_PROGRESS:
                return
            _publish(
                bus,
                workspace_path,
                KNOWLEDGE_EVAL_SETUP_PROGRESS,
                {
                    "run_id": run_id,
                    "phase": "build_graph",
                    "index": int(payload.get("chunk_index") or 0),
                    "total": int(payload.get("chunk_total") or len(graphiti_eps)),
                },
            )

        # Record the Adam-corpus graph build as a ``graph_ingest`` run (per-episode +
        # per-operation nodes) so the ingestion is visible in Graph Runs — previously
        # this path bypassed the ledger entirely (only the answers showed up).
        await gsvc.ingest_chunks(
            graphiti_eps,
            source_role="user_document",
            event_sink=_graph_sink,
            ledger_sink=ledger_sink,
        )
    finally:
        await gsvc.close()
    return len(episodes)


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
) -> QuestionResult:
    """One question → one N-leg fan-out → per-leg scores → one row."""
    results = await service.answer_legs(
        q["question"],
        modes=modes,
        top_k=top_k,
        min_score=min_score,
        filters=filters,
        rewrite=True,
    )
    expected = q["expected_fragments"]
    must_not = q.get("must_not_contain") or []
    legs: dict[str, LegResult] = {}
    scores: dict[str, Any] = {}
    # Preserve the requested column order even though gather returns a dict.
    for mode in modes:
        res = results.get(mode)
        if res is None:
            continue
        score = score_answer(
            res.answer,
            expected,
            no_results=bool(res.no_results),
            must_not_contain=must_not,
        )
        scores[mode] = score
        legs[mode] = LegResult(
            mode=mode,
            mark=score.mark,
            elapsed_ms=int(res.elapsed_ms or 0),
            answer=res.answer or "",
            run_id=getattr(res, "run_id", None),
        )
    return QuestionResult(
        id=q["id"],
        category=q.get("category", ""),
        subcategory=q.get("subcategory", ""),
        question=q["question"],
        requires_graph=bool(q.get("requires_graph")),
        legs=legs,
        delta=_best_graph_delta(scores),
        expected_fragments=expected,
        must_not_contain=must_not,
    )


def _best_graph_delta(scores: dict[str, Any]) -> str:
    """Signed rank delta of the BEST graph leg vs flat — the table's Δ column.

    "+N" when a graph leg (graphiti/mix) beats flat, "-N" when the best graph leg
    still trails flat, "0" on tie or when flat / all graph legs are absent."""
    flat = scores.get("flat")
    graph_marks = [s.mark for m, s in scores.items() if m != "flat"]
    if flat is None or not graph_marks:
        return "0"
    best_graph = max(MARK_RANK.get(mk, 0) for mk in graph_marks)
    diff = best_graph - MARK_RANK.get(flat.mark, 0)
    if diff > 0:
        return f"+{diff}"
    if diff < 0:
        return str(diff)
    return "0"


def category_breakdown(
    rows: list[QuestionResult], modes: list[str]
) -> dict[str, dict[str, Any]]:
    """Per-category × N-leg passing counts — the per-category results table.

    Shape: ``{category: {"total": int, "pass": {leg: count}}}``. Pure so the
    standalone harness + tests can reuse it. ``category`` empty → ``"uncategorized"``."""
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


def _summarize(
    run_id: str, rows: list[QuestionResult], started_at: float, modes: list[str]
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
    # Gate: a graph leg must MEASURABLY beat flat on the requires_graph subset.
    # Needs flat AND at least one graph leg in the run; otherwise the comparison is
    # undefined → "n/a" (e.g. the user ran a single leg).
    graph_modes = [m for m in modes if m != "flat"]
    if "flat" in modes and graph_modes:
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


__all__ = [
    "ADAM_CORPUS_FILE",
    "ADAM_EVAL_TAG",
    "ADAM_QUESTIONS_FILE",
    "ALL_EVAL_MODES",
    "DEFAULT_CORPUS_DIR",
    "DEFAULT_EVAL_MODES",
    "DEFAULT_QUESTIONS_FILE",
    "EVAL_SYNTHETIC_TAG",
    "EvalSummary",
    "LegResult",
    "QuestionResult",
    "adam_point_id",
    "category_breakdown",
    "collect_synthetic_doc_ids",
    "ingest_adam_corpus_via_service",
    "ingest_synthetic_corpus_via_service",
    "load_adam_questions",
    "load_questions",
    "normalize_modes",
    "run_eval",
]
