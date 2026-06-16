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

def _node_for_operation(operation: str) -> str:
    return _NODE_FOR_OPERATION.get(operation or "", _FALLBACK_NODE)


# Node that fires once PER EDGE (graphiti `semaphore_gather`s `resolve_edge`); in
# ``rich`` mode we render one row per edge so each new/merge/INVALIDATE decision is
# individually visible — the **Hybrid** granularity (docs §12.2.1).
RESOLVE_FACTS_NODE = "resolve_facts"

# Episode input-preview budget (#1 — surface the INGESTED TEXT so the admin can visually
# validate extraction against source). Capped so a chunk can't bloat the ledger.
_EPISODE_TEXT_PREVIEW_MAX_RICH = 1500


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
    # The episode parent step's index in the run timeline (set by ``ledger_episode``).
    # Lets the ingest loop key the per-episode trace sidecar to THIS ledger row so the
    # ingest-trace dialog can link them (mirrors the retrieval side's ``entry.step_index``).
    step_index: int = 0

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


@asynccontextmanager
async def knowledge_graph_ingest_ledger(
    *,
    sink: LedgerSink | None,
    document_id: str = "",
) -> AsyncIterator[GraphIngestLedgerRun]:
    """Open a ledger context for one graph-ingest call.

    ``sink is None`` → no-op context. When ``current_run`` is already set (ingest
    invoked as a sub-step of another ledgered op), rows nest under the parent and
    no aggregate ``@run`` row is written here.
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
    accumulator = RunAccumulator(sink=sink, run_id=run_id, inbound_id=document_id or run_id)
    token = current_run.set(accumulator)
    try:
        yield GraphIngestLedgerRun(
            run_id=run_id, nested=False, accumulator=accumulator, sink=sink
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
    text: str = "",
) -> AsyncIterator[EpisodeLedger | None]:
    """Per-episode context: open a parent step + collector; flush nodes on exit.

    Yields the :class:`EpisodeLedger` so the caller can record persist counts after
    ``add_episode`` returns. ``None`` when the run has no sink (caller guards).

    ``text`` is the episode body being ingested; it's surfaced in the step's input
    preview (#1) so the admin can validate extraction against the source passage.
    """
    if run.sink is None:
        yield None
        return

    collector = EpisodeLedger()
    # ``usage`` capture: the episode row carries the ROLLED-UP token usage for all of this
    # episode's internal graphiti work, so it prices + folds into the run aggregate as ONE row
    # (the per-operation breakdown lives only in the trace sidecar now — docs §12.2).
    entry = run.sink.open_entry(
        EPISODE_NODE, {}, None, captures=frozenset({"usage", "decision"})
    )
    # Carry the step index onto the collector so the caller can anchor the ingest-trace
    # sidecar to this episode row (the trace dialog opens from it).
    collector.step_index = int(getattr(entry, "step_index", 0) or 0)
    # Put the readable turn id (e.g. "d3_3") in the episode row's decision_detail so the
    # single-run table — which renders that column but not input_preview — is scannable by turn.
    entry.set_decision("episode", _short_turn_label(chunk_id))
    entry.set_input_preview(
        _episode_input_preview(
            episode_index=episode_index,
            total=total,
            chunk_id=chunk_id,
            title=title,
            reference_time=reference_time,
            text=text,
        ),
        max_len=_EPISODE_TEXT_PREVIEW_MAX_RICH,
    )
    # Buffer graphiti's tracer spans for this episode so we can read the
    # ``add_episode`` rollup (esp. ``edge.invalidated_count`` — the supersession the
    # response-model stream can't see). See ledger_tracer + docs §12.2.1.
    spans: list[SpanRecord] = []
    token_entry = current_entry.set(entry)
    token_episode = current_ingest_episode.set(collector)
    token_spans = current_spans.set(spans)
    try:
        yield collector
    except Exception as exc:
        _apply_episode_span_rollup(collector, spans)
        _record_node_exception(entry, exc)
        _stamp_episode_rollup(entry, collector)
        run.sink.write_rows(entry.rows(include_parent=True))
        raise
    else:
        _apply_episode_span_rollup(collector, spans)
        entry.set_output_preview(_episode_output_preview(collector))
        entry.finish("ok")
        _stamp_episode_rollup(entry, collector)
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


def _rollup_model_id(collector: EpisodeLedger) -> str:
    """Dominant model id for the episode roll-up: the op (or resolve edge) with the most tokens
    wins — graphiti runs the bulk of the work on the medium/extraction model — falling back to
    any non-empty id."""
    best_id, best_toks = "", -1
    for agg in collector.ops.values():
        toks = agg.input_tokens + agg.output_tokens
        if agg.model_id and toks > best_toks:
            best_id, best_toks = agg.model_id, toks
    for item in collector.resolve_items:
        toks = item.input_tokens + item.output_tokens
        if item.model_id and toks > best_toks:
            best_id, best_toks = item.model_id, toks
    return best_id


def _stamp_episode_rollup(entry: LedgerEntry, collector: EpisodeLedger) -> None:
    """Stamp the episode PARENT row with the rolled-up token usage of all its internal graphiti
    LLM work, so it prices as ONE row and folds into the run aggregate.

    Replaces the former per-operation sub-rows (extract/dedupe/resolve_facts/…): the granular
    breakdown now lives only in the ``trace``-tier sidecar (docs §12.2). The roll-up total equals
    the sum of those former priced rows — ``embed``/``persist`` were never priced — so the
    aggregate cost is unchanged. No LLM work (or no usage reported) → row stays decision-only."""
    in_tok = collector.total_input_tokens
    out_tok = collector.total_output_tokens
    if not (in_tok or out_tok):
        return
    model_id = _rollup_model_id(collector)
    provider = model_id.split(":", 1)[0] if ":" in model_id else ""
    entry.add_usage(
        provider=provider, model=model_id, input_tokens=in_tok, output_tokens=out_tok
    )


def _short_turn_label(chunk_id: str) -> str:
    """Distinguishing short label for an episode/turn in ledger previews + the
    episode row's ``decision_detail`` column.

    Readable corpus ids (e.g. ``locomo_conv_43b_d3_3``) share a long common
    prefix, so ``chunk_id[:8]`` collapses every turn to the same string
    (``locomo_c``) and the run table can only tell rows apart by step index. Show
    the last two underscore-delimited segments instead (``d3_3``) so episode rows
    are scannable. Uuid-style chunk ids (no underscore) keep the first-8 short
    hash, unchanged.
    """
    if not chunk_id:
        return "?"
    if "_" in chunk_id:
        return "_".join(chunk_id.split("_")[-2:])
    return chunk_id[:8]


def _episode_input_preview(
    *,
    episode_index: int,
    total: int,
    chunk_id: str,
    title: str,
    reference_time: Any,
    text: str = "",
) -> str:
    label = (title or "").strip() or "<untitled>"
    # Distinguishing turn label (not chunk_id[:8], which is identical for all turns of a
    # readable-id corpus) so the chunk shown in the preview/header actually identifies the turn.
    cid = _short_turn_label(chunk_id)
    ref = ""
    if reference_time is not None:
        try:
            ref = f" · t={reference_time.date().isoformat()}"
        except Exception:
            ref = ""
    head = f"episode {episode_index}/{total} · chunk {cid} · '{label}'{ref}"
    # #1 — append the actual ingested text so it's visible in the episode step (the
    # set_input_preview cap truncates; whitespace is collapsed by the ledger's _preview).
    body = " ".join((text or "").split())
    return f"{head} · text: {body}" if body else head


def _episode_output_preview(collector: EpisodeLedger) -> str:
    inv = f"(+{collector.invalidated_count} invalidated)" if collector.invalidated_count else ""
    return (
        f"entities={collector.persist_nodes} · facts={collector.persist_edges}{inv}"
        f" · llm={collector.total_llm_calls} calls"
        f" · tok={collector.total_input_tokens}i/{collector.total_output_tokens}o"
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
