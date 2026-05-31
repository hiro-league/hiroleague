"""L3 prototype Tools — knowledge graph ingest.

Per the Tools Architecture rule, knowledge-graph operations are exposed as
:class:`Tool` so the same implementation serves CLI / HTTP / agent callers.

This tool reads chunks for a previously-ingested document from the existing
:class:`KnowledgeService` (Qdrant-backed), feeds them through
:class:`GraphIngestService`, and reports stats. The chunk_ids used in the graph
are the Qdrant ``point_id`` values — so graph→evidence lookups in Phase 3 are
a direct id join, no separate mapping table.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from ..domain.model_factory import create_chat_model
from ..domain.preferences import (
    load_preferences,
    resolve_knowledge_graph_disambiguation_llm,
    resolve_knowledge_graph_extraction_llm,
)
from ..domain.workspace import resolve_workspace
from ..services.knowledge import KnowledgeService, create_knowledge_service
from ..services.knowledge.constants import GRAPH_DIR, KNOWLEDGE_DIR, LADYBUG_DB_FILENAME
from ..services.knowledge.graph import GraphStore  # Protocol re-exported
from ..services.knowledge.graph.ingest import (
    ChunkInput,
    GraphEventSink,
    GraphIngestService,
    make_llm_disambiguator,
)
from ..services.knowledge.graph.ladybug_adapter import LadybugGraphStore
from ..services.knowledge.graph.serialize import edge_to_dto, node_to_dto
from .base import Tool, ToolParam

log = Logger.get("SVC.KNOWLEDGE.GRAPH.TOOL")


# Chunks per document we pull in one round-trip from Qdrant. Documents larger
# than this are paged via scroll_offset. 200 covers a typical .md note.
_CHUNK_PAGE_SIZE = 200

# Safety caps for the whole-graph export (the Graph tab's load path). The graph
# is tiny by design; these only exist so a runaway graph can't produce an
# unbounded payload. The response flags ``truncated`` when a cap is hit.
_DEFAULT_NODE_LIMIT = 5000
_DEFAULT_EDGE_LIMIT = 10000


def _resolve_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


def _runtime_workspace(runtime: Any | None) -> Path | None:
    if runtime is None:
        return None
    comm = getattr(runtime, "comm_manager", None)
    ctx = getattr(comm, "ctx", None)
    workspace_path = getattr(ctx, "workspace_path", None)
    return Path(workspace_path) if workspace_path is not None else None


def _runtime_service(runtime: Any | None) -> KnowledgeService | None:
    if runtime is None:
        return None
    comm = getattr(runtime, "comm_manager", None)
    ctx = getattr(comm, "ctx", None)
    manager = getattr(ctx, "knowledge_manager", None)
    if manager is None:
        return None
    return manager.service


def _resolve_service(
    runtime: Any | None, workspace: str | None
) -> tuple[KnowledgeService, Path, bool]:
    service = _runtime_service(runtime)
    if service is not None:
        # Reuse the live service; figure out its workspace_path from runtime.
        ws = _runtime_workspace(runtime) or _resolve_path(workspace)
        return service, ws, False
    workspace_path = _runtime_workspace(runtime) or _resolve_path(workspace)
    return create_knowledge_service(workspace_path), workspace_path, True


def _graph_db_path(workspace_path: Path) -> Path:
    return workspace_path / KNOWLEDGE_DIR / GRAPH_DIR / LADYBUG_DB_FILENAME


def graph_snapshot_payload(
    workspace_path: Path,
    *,
    node_limit: int | None = None,
    edge_limit: int | None = None,
) -> dict[str, Any]:
    """Whole-graph export for the admin Graph tab (sync — Ladybug is sync).

    Returns ``{nodes, edges, truncated, counts}``. When the graph DB does not
    exist yet (no document graph-ingested), returns an empty graph rather than
    creating the DB file — export must never have ingest side effects.
    """
    node_limit = node_limit or _DEFAULT_NODE_LIMIT
    edge_limit = edge_limit or _DEFAULT_EDGE_LIMIT
    db_path = _graph_db_path(workspace_path)
    if not db_path.exists():
        return {"nodes": [], "edges": [], "truncated": False, "counts": {"nodes": 0, "edges": 0}}

    store = LadybugGraphStore.open(db_path)
    try:
        nodes, edges = store.snapshot(node_limit=node_limit, edge_limit=edge_limit)
    finally:
        store.close()
    truncated = len(nodes) >= node_limit or len(edges) >= edge_limit
    return {
        "nodes": [node_to_dto(n) for n in nodes],
        "edges": [edge_to_dto(e) for e in edges],
        "truncated": truncated,
        "counts": {"nodes": len(nodes), "edges": len(edges)},
    }


async def _gather_chunks(
    service: KnowledgeService, document_id: str
) -> tuple[list[ChunkInput], str | None]:
    """Walk all pages of a document's chunks. Returns (chunks, document_title)."""
    chunks: list[ChunkInput] = []
    title: str | None = None
    offset: str | None = None
    while True:
        detail = await service.get_document(
            document_id, chunk_limit=_CHUNK_PAGE_SIZE, chunk_offset=offset
        )
        if detail.document is None:
            raise KeyError(f"Unknown knowledge document: {document_id}")
        title = detail.document.title or title
        for raw in detail.chunks:
            text = str(raw.get("text") or "").strip()
            point_id = str(raw.get("point_id") or "")
            if not text or not point_id:
                continue
            chunks.append(
                ChunkInput(chunk_id=point_id, document_id=document_id, text=text)
            )
        offset = detail.chunk_next_offset
        if not offset:
            break
    return chunks, title


async def _run_graph_ingest_for_documents(
    service: KnowledgeService,
    workspace_path: Path,
    document_ids: list[str],
    *,
    source_role: str,
    on_progress: Any | None = None,
    event_sink: GraphEventSink | None = None,
) -> dict[str, Any]:
    """Shared helper used by the single and batch graph-ingest tools.

    Opens the LadybugDB store + builds the extraction (and optional
    disambiguation) models ONCE, then iterates documents — so a batch of N
    documents pays one set of model/store-open costs, not N.

    Per-document failures are **isolated**: if one document throws, that
    document's entry is marked ``ok=False`` with the error message and the
    batch continues. The store + models stay alive for the remaining docs.

    ``on_progress`` is an optional sync callable invoked after each document
    completes — Phase 5c (streaming) wires it to the event bus so the Eval
    Batch UI updates live without waiting for the full batch. Signature:
    ``on_progress({"index": i, "total": n, "document_id": str, "document_title": str, "ok": bool, "stats": dict|None, "error": str})``.

    ``event_sink`` is an optional ``(event_type, payload)`` callable wired by the
    HTTP layer to the Domain Event Bus; when present the ingest emits per-node /
    per-edge events so the admin Graph tab updates live (graph viz, MVP).
    """
    if not document_ids:
        return {
            "document_count": 0,
            "documents": [],
            "totals": _empty_totals(),
        }

    prefs = load_preferences(workspace_path)
    extraction = resolve_knowledge_graph_extraction_llm(prefs, workspace_path)
    if extraction is None:
        # No model configured — caller-facing error (the caller explicitly asked
        # for graph ingest; silent fall-through would be wrong).
        raise RuntimeError(
            "knowledge_graph_ingest: no extraction model configured. "
            "Set knowledge.answering.model (or llm.default_chat) and "
            "ensure the provider key is configured."
        )
    extract_model = create_chat_model(
        extraction.model_id,
        workspace_path=workspace_path,
        temperature=extraction.temperature,
        max_tokens=extraction.max_tokens,
        thinking=extraction.thinking,
    )
    disambig = resolve_knowledge_graph_disambiguation_llm(prefs, workspace_path)
    disambiguator = None
    if disambig is not None:
        disambig_model = create_chat_model(
            disambig.model_id,
            workspace_path=workspace_path,
            temperature=disambig.temperature,
            max_tokens=disambig.max_tokens,
            thinking=disambig.thinking,
        )
        disambiguator = make_llm_disambiguator(disambig_model)

    store = LadybugGraphStore.open(_graph_db_path(workspace_path))
    # ``event_sink`` (when provided by the HTTP layer) makes the ingest emit live
    # node/edge events so the admin Graph tab pops new elements in real time.
    ingest = GraphIngestService(
        store, workspace_path=workspace_path, event_sink=event_sink
    )
    per_doc: list[dict[str, Any]] = []
    totals = _empty_totals()
    try:
        for index, document_id in enumerate(document_ids):
            entry: dict[str, Any] = {
                "index": index,
                "total": len(document_ids),
                "document_id": document_id,
                "document_title": "",
                "ok": False,
                "stats": None,
                "error": "",
            }
            try:
                chunks, title = await _gather_chunks(service, document_id)
                entry["document_title"] = title or ""
                log.info(
                    "⬇️ graph.ingest — %d chunk(s) from document · doc_id=%s title=%r",
                    len(chunks),
                    document_id,
                    title or "",
                )
                stats = await ingest.ingest_chunks(
                    chunks,
                    source_role=source_role,
                    model=extract_model,
                    model_id=extraction.model_id,
                    disambiguator=disambiguator,
                    document_id=document_id,
                    document_title=title or "",
                )
                stats_dict = stats.as_dict()
                entry["ok"] = True
                entry["stats"] = stats_dict
                _fold_into_totals(totals, stats_dict)
            except Exception as exc:
                # Per-doc failure isolation. Log + record + continue. The caller
                # sees ok=False on this entry; batch totals reflect what succeeded.
                log.warning(
                    "⚠️ graph.ingest — document failed · doc_id=%s · %s",
                    document_id,
                    str(exc)[:200],
                    exc_info=True,
                )
                entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            per_doc.append(entry)
            if on_progress is not None:
                # Notify even on failure so the UI can show the row turning red.
                # Wrap callback errors so progress glitches never abort the batch.
                try:
                    on_progress(dict(entry))
                except Exception:
                    log.exception("⚠️ graph.ingest — on_progress callback failed")
    finally:
        store.close()

    return {
        "document_count": len(document_ids),
        "documents": per_doc,
        "totals": totals,
    }


def _empty_totals() -> dict[str, int]:
    return {
        "entities_created": 0,
        "entities_linked_exact": 0,
        "entities_linked_fuzzy": 0,
        "entities_linked_llm": 0,
        "edges_written": 0,
        "edges_dropped_orphan": 0,
        "llm_extraction_calls": 0,
        "llm_disambiguation_calls": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "chunks_processed": 0,
        "chunks_rejected": 0,
        "chunks_extraction_failed": 0,
    }


def _fold_into_totals(totals: dict[str, int], stats: dict[str, Any]) -> None:
    for key in totals:
        value = stats.get(key)
        if isinstance(value, (int, float)):
            totals[key] += int(value)


class KnowledgeGraphIngestTool(Tool):
    """Build entity/relationship graph nodes for a previously-ingested document.

    L3 prototype. Reads chunks for the document from Qdrant (via the existing
    knowledge service), runs single-call extraction + deterministic-first
    resolution, and writes nodes/edges into the workspace LadybugDB graph.

    Idempotent: re-running on the same document MERGES provenance into existing
    nodes/edges (chunk_ids stay deduped, ordered). Safe to invoke repeatedly.

    For multiple documents in one call, use ``knowledge_graph_ingest_batch`` —
    it pays the model/store-open cost once instead of N times.
    """

    runtime = True
    name = "knowledge_graph_ingest"
    description = (
        "L3 prototype: build entity/relationship graph from a knowledge document's chunks. "
        "Idempotent; pairs with the existing Qdrant evidence pipeline."
    )
    params = {
        "document_id": ToolParam(str, "Knowledge document UUID to graph-ingest"),
        "source_role": ToolParam(
            str,
            "Provenance tag (write-gate). Default: user_document. "
            "Anything outside the allow-list is REJECTED.",
            required=False,
        ),
        "workspace": ToolParam(
            str, "Workspace name (default: registry default)", required=False
        ),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(
        self,
        document_id: str,
        source_role: str = "user_document",
        workspace: str | None = None,
    ) -> dict[str, Any]:
        return asyncio.run(
            self.execute_async(
                document_id=document_id, source_role=source_role, workspace=workspace
            )
        )

    async def execute_async(
        self,
        document_id: str,
        source_role: str = "user_document",
        workspace: str | None = None,
    ) -> dict[str, Any]:
        runtime = getattr(self, "_runtime", None)
        service, workspace_path, owned = _resolve_service(runtime, workspace)
        try:
            batch = await _run_graph_ingest_for_documents(
                service,
                workspace_path,
                [document_id],
                source_role=source_role,
            )
            # Unwrap to the single-document shape this tool has always returned.
            doc = batch["documents"][0] if batch["documents"] else {}
            return {
                "document_id": document_id,
                "document_title": doc.get("document_title", ""),
                "source_role": source_role,
                "stats": doc.get("stats") or _empty_totals(),
                "ok": doc.get("ok", False),
                "error": doc.get("error", ""),
            }
        finally:
            if owned:
                await service.close()


class KnowledgeGraphIngestBatchTool(Tool):
    """Batch variant of ``knowledge_graph_ingest`` — same write side, but
    pays the model/store-open cost ONCE for N documents instead of N times.

    L3 prototype. Used by:

    * Tab 1 Ingest's "Also build entity graph (L3)" checkbox (5f) — when N
      documents are freshly ingested, this tool graph-ingests them in one call.
    * L3 Eval Batch setup (5e) — graph-ingests every synthetic-corpus document
      before the question loop runs.

    Per-document failures are **isolated** — one bad doc doesn't abort the
    batch; its entry is marked ``ok=False`` with the error and processing
    continues. The aggregate ``totals`` reflect what succeeded.
    """

    runtime = True
    name = "knowledge_graph_ingest_batch"
    description = (
        "L3 prototype: graph-ingest N already-ingested documents in one call. "
        "Per-doc failure isolation; idempotent re-run."
    )
    params = {
        # list[str] for the same Gemini-tool-schema reason knowledge_ingest uses it.
        "document_ids": ToolParam(list[str], "Knowledge document UUIDs to graph-ingest"),
        "source_role": ToolParam(
            str,
            "Provenance tag (write-gate). Default: user_document. "
            "Anything outside the allow-list is REJECTED.",
            required=False,
        ),
        "workspace": ToolParam(
            str, "Workspace name (default: registry default)", required=False
        ),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(
        self,
        document_ids: list[str],
        source_role: str = "user_document",
        workspace: str | None = None,
    ) -> dict[str, Any]:
        return asyncio.run(
            self.execute_async(
                document_ids=document_ids, source_role=source_role, workspace=workspace
            )
        )

    async def execute_async(
        self,
        document_ids: list[str],
        source_role: str = "user_document",
        workspace: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(document_ids, list):
            raise ValueError(
                f"document_ids must be a list of strings, got {type(document_ids).__name__}"
            )
        # Dedupe defensively (callers iterating over docs may pass dupes).
        deduped: list[str] = []
        seen: set[str] = set()
        for did in document_ids:
            if not isinstance(did, str) or not did.strip():
                continue
            if did not in seen:
                seen.add(did)
                deduped.append(did)

        runtime = getattr(self, "_runtime", None)
        service, workspace_path, owned = _resolve_service(runtime, workspace)
        try:
            return await _run_graph_ingest_for_documents(
                service,
                workspace_path,
                deduped,
                source_role=source_role,
            )
        finally:
            if owned:
                await service.close()


class KnowledgeGraphExportTool(Tool):
    """Export the whole entity/relationship graph (nodes + edges) for the viz.

    L3 prototype — the **load path** for the admin Graph tab's force-directed
    view. Read-only: opens the workspace LadybugDB graph, returns all nodes and
    edges as plain dicts (``source``/``target`` on edges for force-graph), with
    a ``truncated`` flag + ``counts``. Returns an empty graph (no DB created)
    when nothing has been graph-ingested yet. See docs/knowledge-graph-viz-design.md.
    """

    runtime = True
    name = "knowledge_graph_export"
    description = (
        "L3 prototype: export the whole knowledge graph (nodes + edges) as JSON "
        "for visualization. Read-only; empty graph when none built yet."
    )
    params = {
        "workspace": ToolParam(
            str, "Workspace name (default: registry default)", required=False
        ),
        "node_limit": ToolParam(int, "Max nodes (safety cap)", required=False),
        "edge_limit": ToolParam(int, "Max edges (safety cap)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(
        self,
        workspace: str | None = None,
        node_limit: int | None = None,
        edge_limit: int | None = None,
    ) -> dict[str, Any]:
        return asyncio.run(
            self.execute_async(
                workspace=workspace, node_limit=node_limit, edge_limit=edge_limit
            )
        )

    async def execute_async(
        self,
        workspace: str | None = None,
        node_limit: int | None = None,
        edge_limit: int | None = None,
    ) -> dict[str, Any]:
        runtime = getattr(self, "_runtime", None)
        workspace_path = _runtime_workspace(runtime) or _resolve_path(workspace)
        # Snapshot is sync (Ladybug) — run off the event loop so the HTTP handler
        # doesn't block on the DB read.
        return await asyncio.to_thread(
            graph_snapshot_payload,
            workspace_path,
            node_limit=node_limit,
            edge_limit=edge_limit,
        )


__all__ = [
    "KnowledgeGraphExportTool",
    "KnowledgeGraphIngestBatchTool",
    "KnowledgeGraphIngestTool",
]
