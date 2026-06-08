"""Structured per-stage retrieval trace for the Graphiti fact-search pipeline.

graphiti's ``search()`` computes every stage intermediate (per-leg candidates, BFS
hits, fused/reranked order) in **local variables and discards them** — its tracer
spans expose only *counts*, and ``SearchResults`` exposes only the *final* reranked
list. To evaluate retrieval we need the actual data in/out of each stage, so the
re-hosted pipeline (``graphiti_fact_search``) records it here.

This module owns three things and imports **nothing** from ``graphiti_core`` (the
brain stays rip-out-able, decision G3/G8 — we accept opaque edge objects and read
attributes defensively):

* the :class:`RetrievalTrace` data model (one record per fact search, stages inside),
* a :data:`current_capture` ContextVar — set by ``graph_expand`` around the search
  call (mirrors ``ledger_tracer.current_spans``); ``None`` ⇒ no capture, so the
  default production path is untouched,
* :func:`write_trace_sidecar` — persists the trace JSON sidecar that the Graph-Runs
  retrieval-trace dialog reads back (docs §12.2.3).

The sidecar is the **source of truth for eval** (full data, no truncation); the
ledger keeps only a compact summary + a marker that a trace exists.
"""

from __future__ import annotations

import json
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from hiro_commons.log import Logger

log = Logger.get("SVC.KNOWLEDGE.GRAPH.RETRIEVAL_TRACE")

# Trace schema version — bumped when the stage/record shape changes so the reader
# (endpoint + dialog) can reject or adapt an older on-disk sidecar rather than
# mis-render it. Surfaced in every persisted record.
TRACE_SCHEMA_VERSION = 1

# Sidecar lives beside the graph ledger (workspace/logs/), one JSONL per run so a
# multi-retrieval turn (chat) appends without clobbering; each line is one search.
TRACE_DIRNAME = "retrieval_trace"

_write_lock = Lock()


def _edge_brief(edge: Any, *, score: float | None = None) -> dict[str, Any]:
    """One opaque fact edge → a render-ready, JSON-safe dict (no graphiti import).

    Carries exactly the metadata evaluation needs: identity (``uuid``), the fact
    text + relationship ``name``, the endpoints, the supporting ``episodes`` (==
    chunk_ids), and the bi-temporal window (``valid_at`` / ``invalid_at`` /
    ``expired_at``). ``score`` is the stage score when one exists (fused/reranked);
    the raw bm25/cosine legs return edges without exposing per-item scores, so it is
    ``None`` there and the position in the list is the leg's own ranking."""

    def _iso(value: Any) -> str | None:
        if value is None:
            return None
        iso = getattr(value, "isoformat", None)
        return iso() if callable(iso) else str(value)

    return {
        "uuid": getattr(edge, "uuid", "") or "",
        "fact": getattr(edge, "fact", "") or "",
        "name": getattr(edge, "name", "") or "",
        "source_node_uuid": getattr(edge, "source_node_uuid", "") or "",
        "target_node_uuid": getattr(edge, "target_node_uuid", "") or "",
        "episodes": [str(ep) for ep in (getattr(edge, "episodes", None) or []) if ep],
        "valid_at": _iso(getattr(edge, "valid_at", None)),
        "invalid_at": _iso(getattr(edge, "invalid_at", None)),
        "expired_at": _iso(getattr(edge, "expired_at", None)),
        "score": None if score is None else float(score),
    }


_BASE_ENTITY_LABEL = "Entity"


def _node_entity_type(node: Any) -> str:
    """First non-base ontology label is the entity's type (e.g. ``Person``); else ``Entity``."""
    for label in getattr(node, "labels", None) or []:
        if label and label != _BASE_ENTITY_LABEL:
            return str(label)
    return _BASE_ENTITY_LABEL


def _node_brief(node: Any, *, score: float | None = None) -> dict[str, Any]:
    """One entity node → a render-ready dict (name / type / summary), no graphiti import.

    Entities are the ``node`` lane: an entity has a name + a free-text attribute summary
    (e.g. "Misho turned 50 in June 2026") rather than a fact triple, so the dialog shows
    name/type/summary columns instead of fact/relation/temporal."""
    return {
        "uuid": getattr(node, "uuid", "") or "",
        "name": getattr(node, "name", "") or "",
        "entity_type": _node_entity_type(node),
        "summary": (getattr(node, "summary", "") or "").strip(),
        "score": None if score is None else float(score),
    }


def _episode_brief(ep: Any, *, score: float | None = None) -> dict[str, Any]:
    """One episode (conversation turn / document chunk) → a render-ready dict.

    Episodes are the ``episode`` lane: raw recalled text (BM25), so the dialog shows a
    content snippet + when/where (``valid_at`` event time, ``source``)."""
    valid_at = getattr(ep, "valid_at", None)
    iso = getattr(valid_at, "isoformat", None)
    return {
        "uuid": getattr(ep, "uuid", "") or "",
        "content": getattr(ep, "content", "") or "",
        "source": str(getattr(ep, "source", "") or ""),
        "source_description": getattr(ep, "source_description", "") or "",
        "valid_at": iso() if callable(iso) else None,
        "score": None if score is None else float(score),
    }


@dataclass
class StageRecord:
    """One pipeline stage's inputs, outputs, and metadata.

    ``kind`` is the stable stage id the dialog renders by — one of ``embed``,
    ``candidate`` (one per leg), ``hop``, ``rank``, ``temporal``. ``lane`` is the
    entity type the stage belongs to (``edge`` facts / ``node`` entities / ``episode``
    turns / ``query`` for the shared embed) so the dialog can group the pipeline into
    one lane per type and render items with the right columns. ``meta`` holds scalar
    metadata (method, limits, reranker, counts); ``items`` holds the briefs flowing
    OUT of the stage."""

    kind: str
    label: str
    lane: str = "edge"
    elapsed_ms: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "lane": self.lane,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "meta": self.meta,
            "items": self.items,
        }


@dataclass
class RetrievalTrace:
    """Full per-stage trace of one Graphiti fact search."""

    query: str
    group_id: str
    recipe: str
    temporal: str
    num_results: int
    sim_min_score: float
    k_hop: int
    stages: list[StageRecord] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    def add_stage(self, stage: StageRecord) -> None:
        self.stages.append(stage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TRACE_SCHEMA_VERSION,
            "query": self.query,
            "group_id": self.group_id,
            "recipe": self.recipe,
            "temporal": self.temporal,
            "num_results": self.num_results,
            "sim_min_score": self.sim_min_score,
            "k_hop": self.k_hop,
            "started_at": self.started_at,
            "stages": [s.to_dict() for s in self.stages],
        }


@dataclass
class RetrievalCapture:
    """Capture sink for one fact search — set on :data:`current_capture` by the
    consumer (``graph_expand``) around the search call; the re-hosted pipeline fills
    ``trace`` when present. Mirrors ``ledger_tracer.current_spans`` so the engine-
    agnostic search code never depends on the ledger."""

    trace: RetrievalTrace | None = None


# Active capture for the current task. ``None`` ⇒ the re-host is not engaged and the
# default ``graphiti.search_()`` production path runs unchanged (and tests that pass a
# fake client are unaffected, since they never set this).
current_capture: ContextVar[RetrievalCapture | None] = ContextVar(
    "graph_retrieval_capture", default=None
)


def trace_dir(workspace_path: Path) -> Path:
    """Sidecar directory: ``<workspace>/logs/retrieval_trace`` (beside graph.log)."""
    return Path(workspace_path) / "logs" / TRACE_DIRNAME


def write_trace_sidecar(
    workspace_path: Path,
    *,
    run_id: str,
    step_index: int | str,
    trace: RetrievalTrace,
) -> None:
    """Append one search trace to the run's JSONL sidecar (best-effort, never raises).

    One file per ``run_id`` (``<run_id>.jsonl``); one line per fact search, tagged
    with ``step_index`` so the dialog can link a trace to its ``graph_expand`` ledger
    row. A trace render/IO hiccup must never break retrieval — failures are logged
    and swallowed."""
    try:
        directory = trace_dir(workspace_path)
        directory.mkdir(parents=True, exist_ok=True)
        record = {"run_id": run_id, "step_index": step_index, **trace.to_dict()}
        line = json.dumps(record, ensure_ascii=False)
        path = directory / f"{_safe_run_id(run_id)}.jsonl"
        # Lock the append: concurrent searches in one run (chat) must not interleave a
        # half-written line. A short critical section over a single write is cheap.
        with _write_lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:
        log.warning(
            "⚠️ retrieval trace — sidecar write failed · run_id=%s step=%s",
            run_id,
            step_index,
            exc_info=True,
        )


def read_trace_sidecar(workspace_path: Path, run_id: str) -> list[dict[str, Any]]:
    """Read back all search traces for a run (for the admin endpoint).

    Returns ``[]`` when no sidecar exists (the common case — capture is opt-in). A
    malformed line is skipped, not fatal, so a partially-written tail can't blank the
    whole run's traces."""
    path = trace_dir(workspace_path) / f"{_safe_run_id(run_id)}.jsonl"
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                log.debug("retrieval trace — skipping malformed sidecar line")
                continue
    except OSError:
        log.warning("⚠️ retrieval trace — sidecar read failed · run_id=%s", run_id, exc_info=True)
        return []
    return out


def _safe_run_id(run_id: str) -> str:
    """Filesystem-safe sidecar stem — keep alnum and a small punctuation set."""
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(run_id))
    return cleaned[:120] or "run"


__all__ = [
    "RetrievalCapture",
    "RetrievalTrace",
    "StageRecord",
    "TRACE_SCHEMA_VERSION",
    "current_capture",
    "read_trace_sidecar",
    "trace_dir",
    "write_trace_sidecar",
]
