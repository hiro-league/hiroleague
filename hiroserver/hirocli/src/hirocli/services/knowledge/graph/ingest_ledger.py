"""Ledger lifecycle for Graphiti graph-ingestion runs.

This restores **per-step ingestion visibility** in Graph Runs. Graphiti's
``add_episode`` is a black box from our side — it makes several internal LLM
calls (extract entities, resolve/dedupe, extract facts, date facts, resolve
facts) plus embedder calls, then writes Kuzu. We cannot wrap those internals,
but every LLM call routes through our :class:`GraphitiLLMClient`, which now
tags each call with the Graphiti **response-model name** (the only handle on
*which* step it serves). This module turns that stream into ledger rows:

* :func:`knowledge_graph_ingest_ledger` — opens a run (sets ``current_run``), one
  per ``ingest_chunks`` call (== per document). Writes the aggregate ``@run`` row.
* :func:`ledger_episode` — per-episode context manager. Opens a parent step entry
  and an :class:`EpisodeLedger` collector (via ``current_ingest_episode``); on exit
  it spawns one **sub-step node per operation** (``extract_entities`` …) from the
  collected usage, plus ``embed`` and ``persist`` nodes, and writes them nested
  under the episode step (``N.1``, ``N.2`` …).
* :func:`record_episode_llm_usage` / :func:`record_episode_embed` — the sinks wired
  into the adapter (``on_usage`` / ``on_embed``). No-ops outside an episode context,
  so wiring them globally in ``from_preferences`` is safe for retrieval/memory paths.

Mirrors the retrieval-side :mod:`services.knowledge.ledger_runner` pattern.
Engine-agnostic: it imports the usage value object only, never ``graphiti_core``.

See docs/knowledge-graphiti-pivot-design.md §6 (ingest) and §12 (observability).
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from hirocli.runtime.agent_graph.ledger import (
    LedgerEntry,
    LedgerSink,
    RunAccumulator,
    _record_node_exception,
    current_entry,
    current_run,
)

from .graphiti_adapters import GraphitiLLMUsage
from .ledger_tracer import SpanRecord, current_spans

# Node-name prefix so every ingest row groups + sorts together in Graph Runs,
# matching the retrieval-side convention (``knowledge/parse_query`` etc.).
GRAPH_INGEST_NODE_PREFIX = "knowledge_graph_ingest"
GRAPH_INGEST_RUN_ID_PREFIX = "knowledge_graph_ingest-"

EPISODE_NODE = f"{GRAPH_INGEST_NODE_PREFIX}/episode"

# Graphiti response-model name → ledger node. The model name is what
# ``GraphitiLLMClient`` reports as ``GraphitiLLMUsage.operation``. Anything not
# listed (e.g. a custom entity/edge attribute model) folds into ``attributes``.
_NODE_FOR_OPERATION: dict[str, str] = {
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
_FALLBACK_NODE = "attributes"

# Stable render order for the per-episode sub-steps (sub_step is assigned in the
# order children are spawned, and the Graph Runs reader sorts by it).
_NODE_ORDER: tuple[str, ...] = (
    "extract_entities",
    "resolve_entities",
    "summarize_entities",
    "attributes",
    "extract_facts",
    "date_facts",
    "resolve_facts",
    "completion",
    "embed",
    "persist",
)


def _node_for_operation(operation: str) -> str:
    return _NODE_FOR_OPERATION.get(operation or "", _FALLBACK_NODE)


# Node that fires once PER EDGE (graphiti `semaphore_gather`s `resolve_edge`); in
# ``rich`` mode we render one row per edge so each new/merge/INVALIDATE decision is
# individually visible — the **Hybrid** granularity (docs §12.2.1).
RESOLVE_FACTS_NODE = "resolve_facts"


@dataclass
class _OpAgg:
    """Per-operation aggregate within one episode (the approved granularity)."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_ms: float = 0.0
    model_id: str = ""
    preview: str = ""  # what this op produced (rich mode); first non-empty wins


@dataclass
class _ResolveItem:
    """One ``resolve_facts`` call (one edge) — kept individually for per-item rows."""

    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_ms: float = 0.0
    model_id: str = ""
    preview: str = ""


@dataclass
class EpisodeLedger:
    """Collector for one episode's internal Graphiti work.

    Mutated only on the event-loop thread: LLM usage arrives from ``add_episode``
    (and its gathered sub-tasks, which inherit this context), and embed usage is
    reported by the adapter *after* its worker thread returns. No lock needed.
    """

    ops: dict[str, _OpAgg] = field(default_factory=dict)
    resolve_items: list[_ResolveItem] = field(default_factory=list)
    embed_calls: int = 0
    embed_vectors: int = 0
    embed_elapsed_ms: float = 0.0
    persist_node_names: list[str] = field(default_factory=list)
    persist_edge_facts: list[str] = field(default_factory=list)
    persist_nodes: int = 0
    persist_edges: int = 0
    # From the ``add_episode`` tracer span (docs §12.2.1) — the supersession count
    # is invisible to ``AddEpisodeResults`` (which only returns current edges).
    invalidated_count: int = 0

    def record_llm(self, usage: GraphitiLLMUsage) -> None:
        node = _node_for_operation(usage.operation)
        if node == RESOLVE_FACTS_NODE:
            # Per-edge — keep each call so rich mode can render one row per edge.
            self.resolve_items.append(
                _ResolveItem(
                    input_tokens=max(0, int(usage.input_tokens or 0)),
                    output_tokens=max(0, int(usage.output_tokens or 0)),
                    elapsed_ms=max(0.0, float(usage.elapsed_ms or 0.0)),
                    model_id=usage.model_id or "",
                    preview=usage.preview or "",
                )
            )
            return
        agg = self.ops.get(node)
        if agg is None:
            agg = _OpAgg()
            self.ops[node] = agg
        agg.calls += 1
        agg.input_tokens += max(0, int(usage.input_tokens or 0))
        agg.output_tokens += max(0, int(usage.output_tokens or 0))
        agg.elapsed_ms += max(0.0, float(usage.elapsed_ms or 0.0))
        if usage.model_id and not agg.model_id:
            agg.model_id = usage.model_id
        if usage.preview and not agg.preview:
            agg.preview = usage.preview

    def record_span_rollup(self, *, invalidated: int) -> None:
        """Apply the ``add_episode`` span's supersession count (tracer-sourced)."""
        self.invalidated_count = max(0, int(invalidated or 0))

    def record_embed(self, count: int, elapsed_ms: float) -> None:
        self.embed_calls += 1
        self.embed_vectors += max(0, int(count or 0))
        self.embed_elapsed_ms += max(0.0, float(elapsed_ms or 0.0))

    def set_persist(self, *, node_names: list[str], edge_facts: list[str]) -> None:
        self.persist_node_names = node_names
        self.persist_edge_facts = edge_facts
        self.persist_nodes = len(node_names)
        self.persist_edges = len(edge_facts)

    @property
    def total_input_tokens(self) -> int:
        return sum(a.input_tokens for a in self.ops.values()) + sum(
            r.input_tokens for r in self.resolve_items
        )

    @property
    def total_output_tokens(self) -> int:
        return sum(a.output_tokens for a in self.ops.values()) + sum(
            r.output_tokens for r in self.resolve_items
        )

    @property
    def total_llm_calls(self) -> int:
        return sum(a.calls for a in self.ops.values()) + len(self.resolve_items)


# Active episode collector. Set by :func:`ledger_episode`; the adapter sinks read
# it. ``None`` outside ingest → the sinks no-op (retrieval/memory paths are safe).
current_ingest_episode: ContextVar[EpisodeLedger | None] = ContextVar(
    "graph_ingest_episode", default=None
)


def record_episode_llm_usage(usage: GraphitiLLMUsage) -> None:
    """Adapter ``on_usage`` sink — bucket one LLM call into the active episode."""
    episode = current_ingest_episode.get()
    if episode is not None:
        episode.record_llm(usage)


def record_episode_embed(count: int, elapsed_ms: float) -> None:
    """Adapter ``on_embed`` sink — tally one embedder call into the active episode."""
    episode = current_ingest_episode.get()
    if episode is not None:
        episode.record_embed(count, elapsed_ms)


@dataclass(frozen=True)
class GraphIngestLedgerRun:
    """Resolved ledger identity for one ``ingest_chunks`` call."""

    run_id: str
    nested: bool  # True when reusing a parent ``current_run`` (no aggregate row here)
    accumulator: RunAccumulator | None  # None when nested or sink is None
    sink: LedgerSink | None  # None disables ledgering (tests/CLI without a sink)
    ledger_detail: str = "rich"  # rich = content previews + per-edge resolve_facts


@asynccontextmanager
async def knowledge_graph_ingest_ledger(
    *,
    sink: LedgerSink | None,
    document_id: str = "",
    ledger_detail: str = "rich",
) -> AsyncIterator[GraphIngestLedgerRun]:
    """Open a ledger context for one graph-ingest call.

    ``sink is None`` → no-op context. When ``current_run`` is already set (ingest
    invoked as a sub-step of another ledgered op), rows nest under the parent and
    no aggregate ``@run`` row is written here.
    """
    if sink is None:
        yield GraphIngestLedgerRun(
            run_id="", nested=False, accumulator=None, sink=None, ledger_detail=ledger_detail
        )
        return

    parent = current_run.get()
    if parent is not None:
        yield GraphIngestLedgerRun(
            run_id=parent.run_id,
            nested=True,
            accumulator=None,
            sink=sink,
            ledger_detail=ledger_detail,
        )
        return

    run_id = f"{GRAPH_INGEST_RUN_ID_PREFIX}{uuid.uuid4()}"
    accumulator = RunAccumulator(sink=sink, run_id=run_id, inbound_id=document_id or run_id)
    token = current_run.set(accumulator)
    try:
        yield GraphIngestLedgerRun(
            run_id=run_id,
            nested=False,
            accumulator=accumulator,
            sink=sink,
            ledger_detail=ledger_detail,
        )
    finally:
        current_run.reset(token)


@asynccontextmanager
async def ledger_episode(
    run: GraphIngestLedgerRun,
    *,
    episode_index: int,
    total: int,
    chunk_id: str,
    document_id: str,
    title: str,
    reference_time: Any,
) -> AsyncIterator[EpisodeLedger | None]:
    """Per-episode context: open a parent step + collector; flush nodes on exit.

    Yields the :class:`EpisodeLedger` so the caller can record persist counts after
    ``add_episode`` returns. ``None`` when the run has no sink (caller guards).
    """
    if run.sink is None:
        yield None
        return

    collector = EpisodeLedger()
    entry = run.sink.open_entry(EPISODE_NODE, {}, None, captures=frozenset({"decision"}))
    entry.set_decision("episode", "")
    entry.set_input_preview(
        _episode_input_preview(
            episode_index=episode_index,
            total=total,
            chunk_id=chunk_id,
            title=title,
            reference_time=reference_time,
        )
    )
    # Buffer graphiti's tracer spans for this episode so we can read the
    # ``add_episode`` rollup (esp. ``edge.invalidated_count`` — the supersession the
    # response-model stream can't see). See ledger_tracer + docs §12.2.1.
    spans: list[SpanRecord] = []
    token_entry = current_entry.set(entry)
    token_episode = current_ingest_episode.set(collector)
    token_spans = current_spans.set(spans)
    started = time.perf_counter()
    try:
        yield collector
    except Exception as exc:
        _apply_episode_span_rollup(collector, spans)
        _record_node_exception(entry, exc)
        _flush_episode_children(entry, collector, started, run.ledger_detail)
        run.sink.write_rows(entry.rows(include_parent=True))
        raise
    else:
        _apply_episode_span_rollup(collector, spans)
        entry.set_output_preview(_episode_output_preview(collector))
        entry.finish("ok")
        _flush_episode_children(entry, collector, started, run.ledger_detail)
        run.sink.write_rows(entry.rows(include_parent=True))
    finally:
        current_spans.reset(token_spans)
        current_ingest_episode.reset(token_episode)
        current_entry.reset(token_entry)


def apply_episode_span_rollup(collector: EpisodeLedger) -> None:
    """Public: fold the buffered ``add_episode`` span's supersession count into the
    collector from the active ``current_spans`` context.

    Safe to call right after ``add_episode`` returns (the span is already buffered)
    and again at episode exit — idempotent. Lets the ingest loop read
    ``invalidated_count`` for the run-level stats before the episode context closes."""
    _apply_episode_span_rollup(collector, current_spans.get() or [])


def _apply_episode_span_rollup(collector: EpisodeLedger, spans: list[SpanRecord]) -> None:
    """Pull the ``add_episode`` span's supersession count into the collector."""
    for span in spans:
        if span.name in ("add_episode", "add_episode_bulk"):
            collector.record_span_rollup(
                invalidated=int(span.attributes.get("edge.invalidated_count", 0) or 0)
            )
            return


def _flush_episode_children(
    entry: LedgerEntry,
    collector: EpisodeLedger,
    started: float,
    ledger_detail: str = "rich",
) -> None:
    """Spawn one nested sub-step row per operation (+ resolve_facts + embed + persist).

    ``rich`` adds a per-node content preview (what the step produced) and renders
    ``resolve_facts`` as one row per edge; ``compact`` shows stats only and folds
    ``resolve_facts`` into a single aggregate row. (Hybrid policy, docs §12.2.1.)"""
    rich = ledger_detail != "compact"
    total_elapsed_ms = (time.perf_counter() - started) * 1000.0
    accounted_ms = 0.0

    for node_name in _NODE_ORDER:
        if node_name == "embed":
            if collector.embed_calls:
                child = entry.spawn_child(
                    node=f"{GRAPH_INGEST_NODE_PREFIX}/embed",
                    elapsed_ms=int(collector.embed_elapsed_ms),
                    captures={"decision"},
                )
                child.set_decision("embed")
                child.set_output_preview(
                    f"vectors={collector.embed_vectors} · calls={collector.embed_calls}"
                )
                accounted_ms += collector.embed_elapsed_ms
            continue
        if node_name == "persist":
            continue  # emitted last, after computing the residual elapsed
        if node_name == RESOLVE_FACTS_NODE:
            accounted_ms += _flush_resolve_facts(entry, collector, rich=rich)
            continue

        agg = collector.ops.get(node_name)
        if agg is None:
            continue
        child = entry.spawn_child(
            node=f"{GRAPH_INGEST_NODE_PREFIX}/{node_name}",
            elapsed_ms=int(agg.elapsed_ms),
            captures={"usage", "decision"},
        )
        provider = agg.model_id.split(":", 1)[0] if ":" in agg.model_id else ""
        child.add_usage(
            provider=provider,
            model=agg.model_id,
            input_tokens=agg.input_tokens,
            output_tokens=agg.output_tokens,
        )
        child.set_decision(node_name)
        stats = f"calls={agg.calls} · {agg.input_tokens}i/{agg.output_tokens}o"
        child.set_output_preview(f"{stats} · {agg.preview}" if rich and agg.preview else stats)
        accounted_ms += agg.elapsed_ms

    # ``persist`` carries no model (DB write) — its elapsed is the residual after the
    # LLM/embed calls (Kuzu commit + Graphiti orchestration), so the wall time adds up.
    persist_ms = max(0, int(total_elapsed_ms - accounted_ms))
    persist = entry.spawn_child(
        node=f"{GRAPH_INGEST_NODE_PREFIX}/persist",
        elapsed_ms=persist_ms,
        captures={"decision"},
    )
    persist.set_decision("persist")
    persist.set_output_preview(_persist_preview(collector))


def _flush_resolve_facts(entry: LedgerEntry, collector: EpisodeLedger, *, rich: bool) -> float:
    """Render ``resolve_facts``. Rich = one row per edge; compact = one aggregate row.

    Returns the elapsed_ms accounted, so the caller's persist residual stays correct."""
    items = collector.resolve_items
    if not items:
        return 0.0
    total_ms = sum(r.elapsed_ms for r in items)
    in_tok = sum(r.input_tokens for r in items)
    out_tok = sum(r.output_tokens for r in items)
    model_id = next((r.model_id for r in items if r.model_id), "")
    provider = model_id.split(":", 1)[0] if ":" in model_id else ""

    if rich and len(items) > 1:
        # One row per edge — each carries its own new/merge/INVALIDATE preview.
        for i, item in enumerate(items, start=1):
            child = entry.spawn_child(
                node=f"{GRAPH_INGEST_NODE_PREFIX}/{RESOLVE_FACTS_NODE}[{i}]",
                elapsed_ms=int(item.elapsed_ms),
                captures={"usage", "decision"},
            )
            ip = item.model_id.split(":", 1)[0] if ":" in item.model_id else ""
            child.add_usage(
                provider=ip,
                model=item.model_id,
                input_tokens=item.input_tokens,
                output_tokens=item.output_tokens,
            )
            child.set_decision(RESOLVE_FACTS_NODE)
            stats = f"{item.input_tokens}i/{item.output_tokens}o"
            child.set_output_preview(f"{stats} · {item.preview}" if item.preview else stats)
        return total_ms

    # compact (or single edge) — one aggregate row.
    child = entry.spawn_child(
        node=f"{GRAPH_INGEST_NODE_PREFIX}/{RESOLVE_FACTS_NODE}",
        elapsed_ms=int(total_ms),
        captures={"usage", "decision"},
    )
    child.add_usage(
        provider=provider, model=model_id, input_tokens=in_tok, output_tokens=out_tok
    )
    child.set_decision(RESOLVE_FACTS_NODE)
    preview = f"calls={len(items)} · {in_tok}i/{out_tok}o"
    if rich and items[0].preview:
        preview += f" · {items[0].preview}"
    child.set_output_preview(preview)
    return total_ms


def _episode_input_preview(
    *, episode_index: int, total: int, chunk_id: str, title: str, reference_time: Any
) -> str:
    label = (title or "").strip() or "<untitled>"
    cid = chunk_id[:8] if chunk_id else "?"
    ref = ""
    if reference_time is not None:
        try:
            ref = f" · t={reference_time.date().isoformat()}"
        except Exception:
            ref = ""
    return f"episode {episode_index}/{total} · chunk {cid} · '{label}'{ref}"


def _episode_output_preview(collector: EpisodeLedger) -> str:
    inv = f"(+{collector.invalidated_count} invalidated)" if collector.invalidated_count else ""
    return (
        f"entities={collector.persist_nodes} · facts={collector.persist_edges}{inv}"
        f" · llm={collector.total_llm_calls} calls"
        f" · tok={collector.total_input_tokens}i/{collector.total_output_tokens}o"
    )


def _persist_preview(collector: EpisodeLedger, *, limit: int = 4) -> str:
    nodes = collector.persist_node_names
    edges = collector.persist_edge_facts
    node_part = ", ".join(nodes[:limit]) or "—"
    if len(nodes) > limit:
        node_part += f" (+{len(nodes) - limit})"
    edge_part = " | ".join(edges[:limit]) or "—"
    if len(edges) > limit:
        edge_part += f" (+{len(edges) - limit})"
    inv = f" · invalidated={collector.invalidated_count}" if collector.invalidated_count else ""
    return (
        f"nodes[{collector.persist_nodes}]: {node_part}"
        f" · edges[{collector.persist_edges}]: {edge_part}{inv}"
    )


def preview_ingest_input(
    *,
    document_id: str,
    document_title: str,
    source_role: str,
    episode_count: int,
) -> str:
    """Compact input preview for the aggregate ``@run`` row."""
    title = (document_title or "").strip() or "<untitled>"
    doc = document_id[:12] if document_id else "?"
    return f"doc: '{title}' ({doc}) · role={source_role} · {episode_count} episode(s)"


def preview_ingest_output(stats: Any) -> str:
    """Compact output preview for the aggregate ``@run`` row (``GraphitiIngestStats``)."""
    processed = getattr(stats, "episodes_processed", 0)
    received = getattr(stats, "episodes_received", 0)
    rejected = getattr(stats, "episodes_rejected", 0)
    failed = getattr(stats, "episodes_failed", 0)
    invalidated = getattr(stats, "facts_invalidated", 0)
    tok_in = getattr(stats, "tokens_input", 0)
    tok_out = getattr(stats, "tokens_output", 0)
    return (
        f"episodes={processed}/{received}"
        + (f" (rej={rejected})" if rejected else "")
        + (f" (fail={failed})" if failed else "")
        + f" · entities={getattr(stats, 'entities_total', 0)}"
        + f" · edges={getattr(stats, 'edges_total', 0)}"
        + (f" · invalidated={invalidated}" if invalidated else "")
        + (f" · tok={tok_in}i/{tok_out}o" if (tok_in or tok_out) else "")
    )


def finalize_graph_ingest_run(
    accumulator: RunAccumulator,
    *,
    document_id: str,
    document_title: str,
    source_role: str,
    episode_count: int,
    stats: Any,
    status: str = "completed",
    error_code: str = "",
) -> None:
    """Write the aggregate ``@run`` row for one graph-ingest call."""
    rejected = bool(getattr(stats, "episodes_rejected", 0))
    failed_eps = bool(getattr(stats, "episodes_failed", 0))
    if status == "failed":
        detail = "failed"
    elif rejected:
        detail = "rejected"
    elif failed_eps:
        detail = "episode_errors"
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
            episode_count=episode_count,
        ),
        output_preview=preview_ingest_output(stats),
    )
    accumulator.sink.evict_run(accumulator.run_id)


__all__ = [
    "EPISODE_NODE",
    "GRAPH_INGEST_NODE_PREFIX",
    "GRAPH_INGEST_RUN_ID_PREFIX",
    "EpisodeLedger",
    "GraphIngestLedgerRun",
    "apply_episode_span_rollup",
    "current_ingest_episode",
    "finalize_graph_ingest_run",
    "knowledge_graph_ingest_ledger",
    "ledger_episode",
    "preview_ingest_input",
    "preview_ingest_output",
    "record_episode_embed",
    "record_episode_llm_usage",
]
