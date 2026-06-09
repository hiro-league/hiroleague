"""Structured per-stage ingest trace for the Graphiti ``add_episode`` pipeline.

The WRITE-path mirror of :mod:`retrieval_trace`. graphiti's ``add_episode`` drives
its stages with LLM calls — extract entities → resolve/dedupe entities → extract
facts → date facts → resolve/invalidate facts → summarize — then persists; the
stock client exposes only a coarse ``add_episode`` span (counts) and
``AddEpisodeResults`` (the FINAL nodes/edges). To evaluate ingestion we need the
data flowing **in and out of every stage** (the prompt context + the structured
result), which the stock path discards.

Unlike the read path we **do not re-host** ``add_episode`` (it writes the graph —
a divergent reimplementation would corrupt it). Instead we **observe**: every
ingest stage is an LLM call already routed through ``GraphitiLLMClient``, which
records its full prompt (input) + parsed result (output) into the active
:class:`IngestCapture` when one is set. The optional **non-LLM** dedup auto-merges
(exact/fuzzy collapses that skip the LLM) are captured by a thin pass-through
wrapper (:mod:`graphiti_dedup_trace`). graphiti still performs the real write; we
only watch.

This module owns three things and imports **nothing** from ``graphiti_core`` (the
brain stays rip-out-able, decision G3/G8 — opaque result objects are read
defensively):

* the :class:`IngestStageRecord` / :class:`EpisodeIngestTrace` data model,
* a :data:`current_ingest_capture` ContextVar — set by the ingest loop around each
  ``add_episode`` call (mirrors ``retrieval_trace.current_capture``); ``None`` ⇒ no
  capture, so the default production path is untouched,
* :func:`write_ingest_trace_sidecar` — persists the trace JSONL sidecar that the
  Graph-Runs ingest-trace dialog reads back.

The sidecar is the **source of truth for eval** (full data, no truncation); the
ledger keeps only the per-operation usage rows + a marker that a trace exists.
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

from .retrieval_trace import _edge_brief, _node_brief

log = Logger.get("SVC.KNOWLEDGE.GRAPH.INGEST_TRACE")

# Bumped when the stage/record shape changes so the reader (endpoint + dialog) can
# reject or adapt an older on-disk sidecar rather than mis-render it.
TRACE_SCHEMA_VERSION = 1

# Sidecar dir beside the graph ledger (workspace/logs/); one JSONL per run, one line
# per episode so a multi-episode document appends without clobbering.
INGEST_TRACE_DIRNAME = "ingest_trace"

_write_lock = Lock()

# graphiti response-model name (``GraphitiLLMUsage.operation`` / the structured-output
# model's ``__name__``) → the friendly stage node the dialog renders by. Kept local on
# purpose: ``ingest_ledger`` has its own copy for the ledger lane — duplicated here
# (a few entries) to keep this module dependency-free of the ledger (one-way: the
# ledger may import us, never the reverse). Unknown ops fall back to ``other``.
_STAGE_FOR_OPERATION: dict[str, str] = {
    "ExtractedEntities": "extract_entities",
    "NodeResolutions": "resolve_entities",
    "NodeDuplicate": "resolve_entities",
    "SummarizedEntities": "summarize_entities",
    "ExtractedEdges": "extract_facts",
    "EdgeTimestamps": "date_facts",
    "BatchEdgeTimestamps": "date_facts",
    "EdgeDuplicate": "resolve_facts",
    "completion": "completion",
}

# Per-entity-type attribute extraction (graphiti's ``_extract_entity_attributes``) calls the
# LLM with ``response_model=<the entity type class>``, so its operation name is the type name
# (``Person``…), not a fixed graphiti model. Register the ontology's type names → the
# ``extract_attributes`` stage so those land in the Attributes phase rather than "other". With
# the current FIELD-LESS ontology graphiti skips that call (no fields ⇒ no extraction), so this
# only engages if a type later gains structured fields — registered now so it never silently
# falls through. (Import is our own light module — no graphiti dependency leaks in.)
from .graphiti_ontology import GRAPHITI_ENTITY_TYPES, entity_type_legend  # noqa: E402

for _type_name in GRAPHITI_ENTITY_TYPES:
    _STAGE_FOR_OPERATION.setdefault(_type_name, "extract_attributes")

_FALLBACK_STAGE = "other"

# Human label per stage node, for the dialog header (the order is the ingest pipeline
# order — extraction → resolution → facts → dates → fact-resolution → summary).
_STAGE_LABEL: dict[str, str] = {
    "extract_entities": "Extract entities",
    "resolve_entities": "Resolve / dedupe entities",
    "dedup_entities_auto": "Dedupe entities · non-LLM (fuzzy/exact)",
    "summarize_entities": "Summarize entities",
    "extract_attributes": "Resolve entity attributes",
    "extract_facts": "Extract facts",
    "date_facts": "Date facts",
    "resolve_facts": "Resolve / invalidate facts",
    "completion": "Completion",
    "other": "Other",
}

# Stable render order for the dialog (matches the add_episode pipeline). Stages absent
# from a given episode are simply skipped.
STAGE_ORDER: tuple[str, ...] = (
    "extract_entities",
    "resolve_entities",
    "dedup_entities_auto",
    "extract_facts",
    "date_facts",
    "resolve_facts",
    "summarize_entities",
    "extract_attributes",
    "completion",
    "other",
)


def stage_node_for_operation(operation: str) -> str:
    """Map a graphiti response-model name to its friendly stage node."""
    return _STAGE_FOR_OPERATION.get(operation or "", _FALLBACK_STAGE)


def stage_label(node: str) -> str:
    """Human label for a stage node (dialog header)."""
    return _STAGE_LABEL.get(node, node)


@dataclass
class IngestStageRecord:
    """One ingest stage's input, output, and metadata.

    ``node`` is the stable stage id the dialog groups by (``extract_entities`` …);
    ``operation`` is the raw graphiti response-model name it came from. ``source`` is
    ``llm`` for a captured model call or ``dedup`` for a non-LLM auto-merge recorded by
    the thin wrapper. ``input`` is the stage's input (the prompt messages for an LLM
    stage; the candidate set for a dedup stage); ``output`` is the structured result
    (parsed model dump / dedup decision). Both are stored in full (eval source of
    truth) — the dialog truncates for display."""

    node: str
    label: str
    operation: str = ""
    source: str = "llm"
    elapsed_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    model_id: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    input: Any = None
    output: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "node": self.node,
            "label": self.label,
            "operation": self.operation,
            "source": self.source,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "model_id": self.model_id,
            "meta": self.meta,
            "input": self.input,
            "output": self.output,
        }


@dataclass
class EpisodeIngestTrace:
    """Full per-stage trace of one ``add_episode`` (one episode / chunk).

    ``stages`` is the observed journey (LLM stages + optional non-LLM dedup);
    ``persisted_nodes`` / ``persisted_edges`` are render-ready briefs of what actually
    landed in the graph (from ``AddEpisodeResults``) so the dialog can show the result
    beside the journey; ``invalidated_count`` is the supersession the result alone can't
    expose (from the ``add_episode`` span)."""

    chunk_id: str
    episode_index: int
    total: int
    name: str
    text: str
    group_id: str
    reference_time: str = ""
    started_at: float = field(default_factory=time.time)
    stages: list[IngestStageRecord] = field(default_factory=list)
    persisted_nodes: list[dict[str, Any]] = field(default_factory=list)
    persisted_edges: list[dict[str, Any]] = field(default_factory=list)
    invalidated_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TRACE_SCHEMA_VERSION,
            "chunk_id": self.chunk_id,
            "episode_index": self.episode_index,
            "total": self.total,
            "name": self.name,
            "text": self.text,
            "group_id": self.group_id,
            "reference_time": self.reference_time,
            "started_at": self.started_at,
            "invalidated_count": self.invalidated_count,
            # The active ontology's id→name+description legend, so the dialog can render the
            # extract_entities stage's numeric entity_type_id as the actual type (+ description).
            "entity_types": entity_type_legend(),
            "persisted_nodes": self.persisted_nodes,
            "persisted_edges": self.persisted_edges,
            "stages": [s.to_dict() for s in self.stages],
        }


@dataclass
class IngestCapture:
    """Capture sink for one episode's ``add_episode`` — set on
    :data:`current_ingest_capture` by the ingest loop around the call. The LLM adapter
    (and the optional dedup wrapper) append stages as graphiti runs them; the ingest
    loop assembles the :class:`EpisodeIngestTrace` afterward. Mirrors
    ``retrieval_trace.RetrievalCapture``."""

    stages: list[IngestStageRecord] = field(default_factory=list)

    def add_stage(self, record: IngestStageRecord) -> None:
        # Single-threaded asyncio: ``append`` between awaits is atomic, so concurrent
        # add_episode sub-tasks (per-edge resolve_facts, attribute extraction) that share
        # this capture via the ContextVar reference never tear the list (same guarantee
        # ingest_ledger.EpisodeLedger relies on).
        self.stages.append(record)


# Active capture for the current task. ``None`` ⇒ no ingest trace is engaged and the
# production add_episode path runs unchanged (test fakes never set it).
current_ingest_capture: ContextVar[IngestCapture | None] = ContextVar(
    "graph_ingest_capture", default=None
)


def make_llm_stage(
    *,
    operation: str,
    messages: list[dict[str, Any]],
    output: Any,
    model_id: str,
    elapsed_ms: float,
    input_tokens: int,
    output_tokens: int,
) -> IngestStageRecord:
    """Build an LLM-call stage record (the common case — most stages are LLM calls).

    ``messages`` is the projected prompt (``[{role, content}, …]``) — the stage INPUT;
    ``output`` is the parsed structured result (model dump) — the stage OUTPUT."""
    node = stage_node_for_operation(operation)
    return IngestStageRecord(
        node=node,
        label=stage_label(node),
        operation=operation,
        source="llm",
        elapsed_ms=elapsed_ms,
        input_tokens=max(0, int(input_tokens or 0)),
        output_tokens=max(0, int(output_tokens or 0)),
        model_id=model_id,
        meta={"messages": len(messages)},
        input=messages,
        output=output,
    )


def build_episode_trace(
    *,
    capture: IngestCapture,
    chunk_id: str,
    episode_index: int,
    total: int,
    name: str,
    text: str,
    group_id: str,
    reference_time: str,
    result: Any,
    invalidated_count: int,
) -> EpisodeIngestTrace:
    """Assemble one episode's trace from the captured stages + the persisted result.

    ``result`` is graphiti's ``AddEpisodeResults`` (read defensively — no graphiti
    import); its ``nodes`` / ``edges`` are projected to the same briefs the read-path
    dialog uses, so "what actually landed" renders beside the per-stage journey."""
    nodes = [_node_brief(n) for n in (getattr(result, "nodes", None) or [])]
    edges = [_edge_brief(e) for e in (getattr(result, "edges", None) or [])]
    return EpisodeIngestTrace(
        chunk_id=chunk_id,
        episode_index=episode_index,
        total=total,
        name=name,
        text=text,
        group_id=group_id,
        reference_time=reference_time,
        stages=list(capture.stages),
        persisted_nodes=nodes,
        persisted_edges=edges,
        invalidated_count=max(0, int(invalidated_count or 0)),
    )


def trace_dir(workspace_path: Path) -> Path:
    """Sidecar directory: ``<workspace>/logs/ingest_trace`` (beside graph.log)."""
    return Path(workspace_path) / "logs" / INGEST_TRACE_DIRNAME


def write_ingest_trace_sidecar(
    workspace_path: Path,
    *,
    run_id: str,
    step_index: int | str,
    trace: EpisodeIngestTrace,
) -> None:
    """Append one episode's trace to the run's JSONL sidecar (best-effort, never raises).

    One file per ``run_id`` (``<run_id>.jsonl``); one line per episode, tagged with
    ``step_index`` so the dialog can link a trace to its episode ledger row. A trace
    render/IO hiccup must never break ingestion — failures are logged and swallowed."""
    try:
        directory = trace_dir(workspace_path)
        directory.mkdir(parents=True, exist_ok=True)
        record = {"run_id": run_id, "step_index": step_index, **trace.to_dict()}
        line = json.dumps(record, ensure_ascii=False)
        path = directory / f"{_safe_run_id(run_id)}.jsonl"
        # Lock the append: concurrent episodes are serialized by the Kuzu write lock, but
        # lock here too so a future concurrent writer can't interleave a half-written line.
        with _write_lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:
        log.warning(
            "⚠️ ingest trace — sidecar write failed · run_id=%s step=%s",
            run_id,
            step_index,
            exc_info=True,
        )


def read_ingest_trace_sidecar(workspace_path: Path, run_id: str) -> list[dict[str, Any]]:
    """Read back all episode traces for a run (for the admin endpoint).

    Returns ``[]`` when no sidecar exists (the common case — capture is opt-in). A
    malformed line is skipped, not fatal."""
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
                log.debug("ingest trace — skipping malformed sidecar line")
                continue
    except OSError:
        log.warning("⚠️ ingest trace — sidecar read failed · run_id=%s", run_id, exc_info=True)
        return []
    return out


def _safe_run_id(run_id: str) -> str:
    """Filesystem-safe sidecar stem — keep alnum and a small punctuation set."""
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(run_id))
    return cleaned[:120] or "run"


__all__ = [
    "EpisodeIngestTrace",
    "INGEST_TRACE_DIRNAME",
    "IngestCapture",
    "IngestStageRecord",
    "STAGE_ORDER",
    "TRACE_SCHEMA_VERSION",
    "build_episode_trace",
    "current_ingest_capture",
    "make_llm_stage",
    "read_ingest_trace_sidecar",
    "stage_label",
    "stage_node_for_operation",
    "trace_dir",
    "write_ingest_trace_sidecar",
]
