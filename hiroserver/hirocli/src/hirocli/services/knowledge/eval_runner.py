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
    MARK_PASS,
    MARK_RANK,
    Score,
    delta_mark,
    score_answer,
)

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


@dataclass(frozen=True)
class QuestionResult:
    """Per-question outcome captured for the aggregate summary."""

    id: str
    category: str
    question: str
    requires_graph: bool
    flat_mark: str
    flat_elapsed_ms: int
    flat_answer: str
    flat_run_id: str | None
    graph_mark: str
    graph_elapsed_ms: int
    graph_answer: str
    graph_run_id: str | None
    delta: str

    def to_payload(self, *, index: int, total: int) -> dict[str, Any]:
        """Event payload shape consumed by the Eval Batch UI.

        ``flat.run_id`` / ``graph.run_id`` let the UI render per-leg
        "Open in Graph Runs" links — each leg has its own knowledge_answer
        ledger run (from ``knowledge_answer_ledger``), so the user can drill
        into whichever leg's trace is interesting."""
        return {
            "index": index,
            "total": total,
            "id": self.id,
            "category": self.category,
            "question": self.question,
            "requires_graph": self.requires_graph,
            "flat": {
                "mark": self.flat_mark,
                "elapsed_ms": self.flat_elapsed_ms,
                "answer_preview": _preview(self.flat_answer, 200),
                "run_id": self.flat_run_id,
            },
            "graph": {
                "mark": self.graph_mark,
                "elapsed_ms": self.graph_elapsed_ms,
                "answer_preview": _preview(self.graph_answer, 200),
                "run_id": self.graph_run_id,
            },
            "delta": self.delta,
        }


@dataclass
class EvalSummary:
    """Aggregate output of one eval run — the gate verdict's evidence."""

    run_id: str
    total_questions: int
    flat_passing: int
    graph_passing: int
    requires_graph_total: int
    requires_graph_flat_passing: int
    requires_graph_graph_passing: int
    graph_wins: int
    graph_loses: int
    ties: int
    gate: str  # "proceed" | "pivot"
    elapsed_ms: int
    questions: list[QuestionResult] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "total_questions": self.total_questions,
            "flat_passing": self.flat_passing,
            "graph_passing": self.graph_passing,
            "requires_graph_total": self.requires_graph_total,
            "requires_graph_flat_passing": self.requires_graph_flat_passing,
            "requires_graph_graph_passing": self.requires_graph_graph_passing,
            "graph_wins": self.graph_wins,
            "graph_loses": self.graph_loses,
            "ties": self.ties,
            "gate": self.gate,
            "elapsed_ms": self.elapsed_ms,
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
        expected = row.get("expected_fragments")
        if expected is None or not isinstance(expected, list):
            raise ValueError(
                f"{target}: row {i} ({qid}): expected_fragments must be a list "
                f"(use [] for negative-control rows)"
            )
        out.append(
            {
                "id": qid,
                "category": str(row.get("category") or ""),
                "question": qtext,
                "expected_fragments": [str(f) for f in expected],
                "requires_graph": bool(row.get("requires_graph")),
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
        },
    )

    rows: list[QuestionResult] = []
    try:
        for index, q in enumerate(questions):
            result = await _run_one_question(
                service,
                q,
                filters=eval_filters,
                top_k=top_k,
                min_score=min_score,
            )
            rows.append(result)
            _publish(
                bus,
                workspace_path,
                KNOWLEDGE_EVAL_QUESTION_COMPLETED,
                result.to_payload(index=index, total=total),
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

    summary = _summarize(rid, rows, started_at)
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
        {"phase": "ingest_synthetic", "file_count": len(paths)},
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
# Internals
# ---------------------------------------------------------------------------


async def _run_one_question(
    service: Any,
    q: dict[str, Any],
    *,
    filters: dict[str, Any],
    top_k: int | None,
    min_score: float | None,
) -> QuestionResult:
    """One question → one compare → two scores → one row."""
    comparison = await service.compare(
        q["question"],
        top_k=top_k,
        min_score=min_score,
        filters=filters,
        rewrite=True,
    )
    expected = q["expected_fragments"]
    flat_score = score_answer(
        comparison.flat.answer, expected, no_results=bool(comparison.flat.no_results)
    )
    graph_score = score_answer(
        comparison.graph.answer, expected, no_results=bool(comparison.graph.no_results)
    )
    return QuestionResult(
        id=q["id"],
        category=q.get("category", ""),
        question=q["question"],
        requires_graph=bool(q.get("requires_graph")),
        flat_mark=flat_score.mark,
        flat_elapsed_ms=int(comparison.flat.elapsed_ms or 0),
        flat_answer=comparison.flat.answer or "",
        flat_run_id=getattr(comparison.flat, "run_id", None),
        graph_mark=graph_score.mark,
        graph_elapsed_ms=int(comparison.graph.elapsed_ms or 0),
        graph_answer=comparison.graph.answer or "",
        graph_run_id=getattr(comparison.graph, "run_id", None),
        delta=delta_mark(flat_score, graph_score),
    )


def _summarize(run_id: str, rows: list[QuestionResult], started_at: float) -> EvalSummary:
    """Compute the gate + aggregate counts the UI/CLI surfaces."""
    flat_passing = sum(1 for r in rows if r.flat_mark in (MARK_PASS, "🛇"))
    graph_passing = sum(1 for r in rows if r.graph_mark in (MARK_PASS, "🛇"))
    requires = [r for r in rows if r.requires_graph]
    req_flat = sum(1 for r in requires if r.flat_mark in (MARK_PASS, "🛇"))
    req_graph = sum(1 for r in requires if r.graph_mark in (MARK_PASS, "🛇"))
    wins = sum(
        1 for r in rows if MARK_RANK.get(r.graph_mark, 0) > MARK_RANK.get(r.flat_mark, 0)
    )
    loses = sum(
        1 for r in rows if MARK_RANK.get(r.graph_mark, 0) < MARK_RANK.get(r.flat_mark, 0)
    )
    ties = len(rows) - wins - loses
    # Strict gate: graph must MEASURABLY win on the requires_graph subset.
    gate = "proceed" if req_graph > req_flat else "pivot"
    return EvalSummary(
        run_id=run_id,
        total_questions=len(rows),
        flat_passing=flat_passing,
        graph_passing=graph_passing,
        requires_graph_total=len(requires),
        requires_graph_flat_passing=req_flat,
        requires_graph_graph_passing=req_graph,
        graph_wins=wins,
        graph_loses=loses,
        ties=ties,
        gate=gate,
        elapsed_ms=int((time.perf_counter() - started_at) * 1000),
        questions=list(rows),
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
    "DEFAULT_CORPUS_DIR",
    "DEFAULT_QUESTIONS_FILE",
    "EVAL_SYNTHETIC_TAG",
    "EvalSummary",
    "QuestionResult",
    "collect_synthetic_doc_ids",
    "ingest_synthetic_corpus_via_service",
    "load_questions",
    "run_eval",
]
