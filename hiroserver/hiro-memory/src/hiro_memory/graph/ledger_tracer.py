"""Bridge graphiti-core's ``Tracer`` spans into Hiro's Graph-Runs ledger.

graphiti instruments **ingest** (`add_episode`), **retrieval** (`search`), and
every **`llm.generate`** with its own ``Tracer`` ABC — `start_span(name) -> span`
where the span has `add_attributes` / `set_status` / `record_exception`. This is
the **only** hook that decomposes `search()` (which makes ~no LLM calls, so the
ingest-side `on_usage`/response-model trick yields nothing there).

graphiti's ``create_tracer`` only accepts an **OpenTelemetry** tracer (it would
discard a custom ``Tracer``), so we do **not** pass this via ``Graphiti(tracer=…)``.
The service overrides ``g.tracer`` / ``g.clients.tracer`` /
``llm_client.set_tracer`` **after** construction (see ``graphiti_service``).

This tracer is intentionally dumb: it appends each **allowlisted** completed span
(name, attributes, elapsed, status) to the :data:`current_spans` ContextVar list,
when one is active. The consumers own the rendering:

* **retrieval** — ``graph_expand`` (``agent/graph.py``) opens a list around the
  search call, then turns the ``search.*`` records into ledger sub-steps (§12.2.2).
* **ingest** — ``ledger_episode`` (``ingest_ledger.py``) opens a list around
  ``add_episode`` and reads the ``add_episode`` record's ``edge.invalidated_count``
  (+ node/edge counts). The per-op LLM rows still come from the ``on_usage``
  collector — tokens live there, not on the span.

``current_spans is None`` → the tracer no-ops, so every other graphiti caller
(memory paths, snapshots) is unaffected. Engine-agnostic: imports nothing from
``graphiti_core``. See docs/knowledge-graphiti-pivot-design.md §12.2.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

from hiro_commons.log import Logger

log = Logger.get("SVC.KNOWLEDGE.GRAPH.LEDGER_TRACER")


@dataclass
class SpanRecord:
    """One completed graphiti span — the unit the consumers render from."""

    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    status: str = "ok"
    error: str = ""


# Active span buffer. A consumer (graph_expand / ledger_episode) sets a fresh list
# around the graphiti call it wants to decompose; this tracer appends allowlisted
# spans here. ``None`` → the tracer no-ops (other callers unaffected).
current_spans: ContextVar[list[SpanRecord] | None] = ContextVar(
    "graph_ledger_spans", default=None
)


@dataclass
class RerankUsage:
    """Cross-encoder rerank usage for one search — priced as the ``rerank`` ledger node.

    Graphiti's ``cross_encoder`` reranker (``HiroRerankerCrossEncoder``) reports here via the
    injected ``on_rank`` sink. ``processed_tokens`` follows Voyage's billed shape
    (``query_tokens × doc_count + Σ doc_tokens``); Cohere-style per-search-unit pricing ignores
    it (the ledger prices with ``search_units=1``). ``model_id`` is the prefixed catalog id so
    ``_with_cost`` can resolve + price it (local rerankers miss the catalog → $0, correctly free).
    """

    model_id: str = ""
    processed_tokens: int = 0
    calls: int = 0
    elapsed_ms: float = 0.0


# Active rerank-usage accumulator, set by the SAME consumers that set ``current_spans``
# (graph_expand / memory recall) around a search. ``None`` → ``record_rerank_usage`` no-ops, so
# ingestion and non-ledgered callers are unaffected.
current_rerank_usage: ContextVar[RerankUsage | None] = ContextVar(
    "graph_ledger_rerank_usage", default=None
)


def record_rerank_usage(model_id: str, processed_tokens: int, elapsed_ms: float) -> None:
    """Adapter ``on_rank`` sink — fold one cross-encoder rerank call into the active accumulator.

    No-op outside a search that opened ``current_rerank_usage``. Engine-agnostic: the adapter
    calls this through an injected callable, never importing the ledger (same shape as ``on_embed``).
    """
    acc = current_rerank_usage.get()
    if acc is None:
        return
    if model_id and not acc.model_id:
        acc.model_id = model_id
    acc.processed_tokens += max(0, int(processed_tokens or 0))
    acc.elapsed_ms += max(0.0, float(elapsed_ms or 0.0))
    acc.calls += 1

# Innermost graphiti tracer span currently active (set by ``LedgerTracer.start_span``). Lets a
# lane-blind callee (e.g. the cross-encoder adapter, which graphiti calls inside
# ``search.node_search.cross_encoder_rank``) read the lane to label its own LangSmith span.
# ``None`` when no graphiti span is active (tracer not attached / outside a graphiti call).
current_graphiti_span: ContextVar[str | None] = ContextVar("graphiti_active_span", default=None)


# Spans we keep: ``search.*`` (retrieval phases) + ``add_episode`` (ingest rollup).
# ``llm.generate`` is intentionally excluded — its tokens arrive via the on_usage
# sink, and we don't want a buffered row per internal LLM call here.
_KEEP_EXACT = frozenset({"add_episode", "add_episode_bulk", "search"})
_KEEP_PREFIX = ("search.",)


def _keep(name: str) -> bool:
    return name in _KEEP_EXACT or name.startswith(_KEEP_PREFIX)


class _LedgerSpan:
    """graphiti ``TracerSpan`` — accumulates attributes; emitted on context exit."""

    __slots__ = ("attributes", "status", "error")

    def __init__(self) -> None:
        self.attributes: dict[str, Any] = {}
        self.status = "ok"
        self.error = ""

    def add_attributes(self, attributes: dict[str, Any]) -> None:
        # graphiti calls this 1+ times per span with count/dim/uuid attrs.
        try:
            self.attributes.update(attributes or {})
        except Exception:  # never break the graphiti call over a ledger attr
            log.debug("ledger tracer — add_attributes ignored", exc_info=True)

    def set_status(self, status: str, description: str | None = None) -> None:
        if status:
            self.status = status
        if description:
            self.error = str(description)[:200]

    def record_exception(self, exception: Exception) -> None:
        self.error = str(exception)[:200]


class LedgerTracer:
    """graphiti ``Tracer`` — buffers allowlisted spans into :data:`current_spans`."""

    @contextmanager
    def start_span(self, name: str) -> Iterator[_LedgerSpan]:
        span = _LedgerSpan()
        started = time.perf_counter()
        # Publish this span as the innermost active graphiti span so a lane-blind callee
        # (cross-encoder adapter) can read the lane from e.g. ``search.node_search.*``.
        active_token = current_graphiti_span.set(name)
        try:
            yield span
        finally:
            current_graphiti_span.reset(active_token)
            # A ledger hiccup must never abort an ingest/search.
            try:
                buffer = current_spans.get()
                if buffer is not None and _keep(name):
                    buffer.append(
                        SpanRecord(
                            name=name,
                            attributes=dict(span.attributes),
                            elapsed_ms=(time.perf_counter() - started) * 1000.0,
                            status=span.status,
                            error=span.error,
                        )
                    )
            except Exception:
                log.warning("⚠️ ledger tracer — span record failed · %s", name, exc_info=True)


__all__ = [
    "LedgerTracer",
    "RerankUsage",
    "current_graphiti_span",
    "SpanRecord",
    "current_rerank_usage",
    "current_spans",
    "record_rerank_usage",
]
