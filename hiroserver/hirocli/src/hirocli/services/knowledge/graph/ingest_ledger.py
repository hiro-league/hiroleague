"""Ledger lifecycle for L3 graph ingestion runs.

Mirrors the retrieval-side :mod:`services.knowledge.ledger_runner` pattern:

* :func:`knowledge_graph_ingest_ledger` opens an async context that owns a
  :class:`RunAccumulator` (sets ``current_run``), so per-chunk steps decorated
  with :func:`ledger_step` automatically fold into that run.
* :func:`ledger_step` is the per-step async context manager — open an entry,
  let the caller populate it, finish/write on exit. No-op when ``sink`` is None
  (preserves the "sink optional → no ledger" backward-compatible path).
* :func:`finalize_graph_ingest_run` writes the aggregate ``@run`` row at the
  end (counts, totals, status), matching ``finalize_standalone_run``.

This module is **engine-agnostic** — it doesn't know about Ladybug, the
extractor, or the resolver. It just provides the surfaces ``ingest.py`` calls
to make each per-chunk step visible in Graph Runs.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterable

from hirocli.runtime.agent_graph.ledger import (
    LedgerEntry,
    LedgerSink,
    RunAccumulator,
    _record_node_exception,
    current_entry,
    current_run,
)

# Prefix on every ledger node name so rows group + sort together in Graph Runs,
# matching the retrieval-side convention (``knowledge/parse_query``, etc.).
GRAPH_INGEST_NODE_PREFIX = "knowledge_graph_ingest"
GRAPH_INGEST_RUN_ID_PREFIX = "knowledge_graph_ingest-"


@dataclass(frozen=True)
class GraphIngestLedgerRun:
    """Resolved ledger identity for one ``GraphIngestService.ingest_chunks`` call."""

    run_id: str
    nested: bool                   # True when reusing a parent ``current_run`` (no aggregate row)
    accumulator: RunAccumulator | None  # None when nested or sink is None
    sink: LedgerSink | None        # the sink ``ledger_step`` should write to (None disables)


def preview_ingest_input(
    *,
    document_id: str,
    document_title: str,
    source_role: str,
    chunks_count: int,
) -> str:
    """Compact input preview for the aggregate run row."""
    title = (document_title or "").strip() or "<untitled>"
    return (
        f"doc: '{title}' ({document_id[:12] if document_id else '?'})"
        f" · role={source_role} · {chunks_count} chunk(s)"
    )


def preview_ingest_output(stats: Any) -> str:
    """Compact output preview for the aggregate run row.

    ``stats`` is a duck-typed object exposing the public counters on
    ``GraphIngestStats``; kept loose so this module doesn't import the service.
    """
    branches = "+".join(
        f"{name}{val}"
        for name, val in (
            ("ex", getattr(stats, "entities_linked_exact", 0)),
            ("fz", getattr(stats, "entities_linked_fuzzy", 0)),
            ("ll", getattr(stats, "entities_linked_llm", 0)),
            ("ne", getattr(stats, "entities_created", 0)),
        )
        if val
    ) or "none"
    return (
        f"chunks={getattr(stats, 'chunks_processed', 0)}/{getattr(stats, 'chunks_received', 0)}"
        + (f" (rej={stats.chunks_rejected})" if getattr(stats, "chunks_rejected", 0) else "")
        + (f" (extfail={stats.chunks_extraction_failed})" if getattr(stats, "chunks_extraction_failed", 0) else "")
        + f" · entities[{branches}]"
        + f" · edges={getattr(stats, 'edges_written', 0)}"
        + (f" (orphan={stats.edges_dropped_orphan})" if getattr(stats, "edges_dropped_orphan", 0) else "")
        + f" · llm: {getattr(stats, 'llm_extraction_calls', 0)}ext"
        + f"+{getattr(stats, 'llm_disambiguation_calls', 0)}dis"
        + f" · tok: {getattr(stats, 'total_input_tokens', 0)}i/{getattr(stats, 'total_output_tokens', 0)}o"
    )


@asynccontextmanager
async def knowledge_graph_ingest_ledger(
    *,
    sink: LedgerSink | None,
    document_id: str = "",
) -> AsyncIterator[GraphIngestLedgerRun]:
    """Open a ledger context for one graph-ingest call.

    When ``sink`` is None, the context is a no-op (yields a sentinel that
    ``ledger_step`` silently ignores) — keeps the service callable without
    a sink in tests.

    When ``current_run`` is already set (e.g. graph ingest invoked as a
    sub-step of another ledgered operation in the future), the new entries
    nest under the parent ``run_id`` and no aggregate row is written here.
    """
    if sink is None:
        yield GraphIngestLedgerRun(run_id="", nested=False, accumulator=None, sink=None)
        return

    parent = current_run.get()
    if parent is not None:
        yield GraphIngestLedgerRun(
            run_id=parent.run_id, nested=True, accumulator=None, sink=sink
        )
        return

    run_id = f"{GRAPH_INGEST_RUN_ID_PREFIX}{uuid.uuid4()}"
    accumulator = RunAccumulator(
        sink=sink,
        run_id=run_id,
        # Use the document id (when given) as the inbound correlation id so a
        # tail-the-log workflow can group all rows for the same ingest.
        inbound_id=document_id or run_id,
    )
    token = current_run.set(accumulator)
    try:
        yield GraphIngestLedgerRun(
            run_id=run_id, nested=False, accumulator=accumulator, sink=sink
        )
    finally:
        current_run.reset(token)


def finalize_graph_ingest_run(
    accumulator: RunAccumulator,
    *,
    document_id: str,
    document_title: str,
    source_role: str,
    chunks_count: int,
    stats: Any,
    status: str = "completed",
    error_code: str = "",
) -> None:
    """Write the aggregate ``@run`` row for one graph-ingest call.

    Decision detail communicates the *shape* of the outcome at a glance:
    ``rejected`` / ``extraction_errors`` / ``graph_ingest`` (clean) / ``failed``.
    """
    rejected = bool(getattr(stats, "chunks_rejected", 0))
    ext_failed = bool(getattr(stats, "chunks_extraction_failed", 0))
    if status == "failed":
        detail = "failed"
    elif rejected:
        detail = "rejected"
    elif ext_failed:
        detail = "extraction_errors"
    else:
        detail = "graph_ingest"
    effective_status = "rejected" if rejected and status == "completed" else status
    accumulator.sink.write_run_row(
        accumulator,
        status=effective_status,
        error_code=error_code,
        decision_kind=effective_status,
        decision_detail=detail,
        input_preview=preview_ingest_input(
            document_id=document_id,
            document_title=document_title,
            source_role=source_role,
            chunks_count=chunks_count,
        ),
        output_preview=preview_ingest_output(stats),
    )
    accumulator.sink.evict_run(accumulator.run_id)


@asynccontextmanager
async def ledger_step(
    sink: LedgerSink | None,
    node_name: str,
    *,
    captures: Iterable[str] | None = None,
) -> AsyncIterator[LedgerEntry | None]:
    """Per-step ledger context manager.

    Mirrors what the LangGraph node wrapper does (``_run_wrapped_plain_async``)
    but as an explicit ``async with`` so we can use it in a plain async loop
    without making the loop a LangGraph.

    Yields the open :class:`LedgerEntry` so the caller can populate
    ``set_decision`` / ``set_input_preview`` / ``set_output_preview`` /
    ``add_usage`` / ``set_error`` directly. When ``sink`` is None, yields
    ``None`` and the body is responsible for ``if entry is not None:`` guards
    (consistent with how LangGraph nodes do it via ``current_entry.get()``).
    """
    if sink is None:
        yield None
        return

    full_node = f"{GRAPH_INGEST_NODE_PREFIX}/{node_name}"
    entry = sink.open_entry(full_node, {}, None, captures=frozenset(captures or ()))
    token = current_entry.set(entry)
    try:
        yield entry
    except Exception as exc:
        _record_node_exception(entry, exc)
        sink.write_rows(entry.rows(include_parent=True))
        raise
    else:
        entry.finish("ok")
        sink.write_rows(entry.rows(include_parent=True))
    finally:
        current_entry.reset(token)


def format_resolution_preview(
    resolutions: list[tuple[str, str, str]],  # (mention_name, branch, node_id_short)
    *,
    limit: int = 5,
) -> str:
    """Compact per-mention rendering for the resolve step's output preview.

    e.g. ``Maya→exact·p_maya · Selim→exact·p_selim · Paris→created · (+3 more)``"""
    if not resolutions:
        return "no mentions"
    parts: list[str] = []
    for name, branch, node_id in resolutions[:limit]:
        short_id = node_id[:10] if node_id else "?"
        # Short branch labels (output_preview is 280 chars max).
        short_branch = {
            "exact_link": "exact",
            "fuzzy_link": "fuzzy",
            "llm_link": "llm",
            "created": "new",
        }.get(branch, branch)
        parts.append(f"{name}→{short_branch}·{short_id}")
    rendered = " · ".join(parts)
    if len(resolutions) > limit:
        rendered += f" · (+{len(resolutions) - limit} more)"
    return rendered


__all__ = [
    "GRAPH_INGEST_NODE_PREFIX",
    "GRAPH_INGEST_RUN_ID_PREFIX",
    "GraphIngestLedgerRun",
    "finalize_graph_ingest_run",
    "format_resolution_preview",
    "knowledge_graph_ingest_ledger",
    "ledger_step",
    "preview_ingest_input",
    "preview_ingest_output",
]
