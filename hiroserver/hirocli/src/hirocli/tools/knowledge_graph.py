"""Knowledge graph Tools — Graphiti ingest + export.

Per the Tools Architecture rule, knowledge-graph operations are exposed as
:class:`Tool` so one implementation serves CLI / HTTP / agent callers.

The ingest tool reads a document's chunks from the existing
:class:`KnowledgeService` (Qdrant-backed) and ingests them as **Graphiti
episodes** (``uuid = point_id``), via :class:`GraphitiMemoryService`. Graphiti
dedupes by uuid, so re-running on the same document is idempotent.

The export tool is the admin Graph tab's load path. The real Kuzu snapshot →
Graphiti-schema DTO mapping lands in Phase 4
(docs/knowledge-graphiti-pivot-design.md §5.6); until then it returns an empty
graph so the tab loads without error.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from ..domain.preferences import load_preferences
from ..domain.workspace import resolve_workspace
from ..runtime.agent_graph.ledger import LedgerSink
from ..services.knowledge import KnowledgeService, create_knowledge_service
from ..services.knowledge.graph import (
    GraphitiEpisodeInput,
    GraphitiMemoryService,
    graphiti_db_path,
)
from ..services.knowledge.graph.graphiti_ingest import GraphEventSink
from ..services.knowledge.graph.graphiti_serialize import build_graph_dtos
from ..services.knowledge.graph.graphiti_service import (
    read_graph_group_ids,
    read_graph_snapshot,
)
from .base import Tool, ToolParam

log = Logger.get("SVC.KNOWLEDGE.GRAPH.TOOL")


# Chunks per document we pull in one round-trip from Qdrant. Documents larger
# than this are paged via scroll_offset. 200 covers a typical .md note.
_CHUNK_PAGE_SIZE = 200

# Safety caps for the whole-graph export (the Graph tab's load path). The graph is
# small by design; these only exist so a runaway graph can't produce an unbounded
# payload. The response flags ``truncated`` when a cap is hit.
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
        ws = _runtime_workspace(runtime) or _resolve_path(workspace)
        return service, ws, False
    workspace_path = _runtime_workspace(runtime) or _resolve_path(workspace)
    return create_knowledge_service(workspace_path), workspace_path, True


async def graph_snapshot_payload(
    workspace_path: Path,
    *,
    node_limit: int | None = None,
    edge_limit: int | None = None,
    group_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Whole-graph export for the admin Graph tab (Graphiti → wire DTO).

    Read-only: reads every entity node + RELATES_TO fact from Kuzu (no models),
    maps to the viz DTO (entities + relations + temporal windows). ``group_ids`` selects the
    partition — default knowledge group, or a ``mem_{user}_{character}`` conversation-memory
    group. Returns an empty graph when none is built yet — never an ingest side effect.
    ``truncated`` flags a safety-cap hit.
    """
    node_limit = node_limit or _DEFAULT_NODE_LIMIT
    edge_limit = edge_limit or _DEFAULT_EDGE_LIMIT
    nodes, edges, chunk_to_document = await read_graph_snapshot(
        graphiti_db_path(workspace_path),
        node_limit=node_limit,
        edge_limit=edge_limit,
        group_ids=group_ids,
    )
    truncated = len(nodes) >= node_limit or len(edges) >= edge_limit
    dtos = build_graph_dtos(nodes, edges, chunk_to_document=chunk_to_document)
    return {
        "nodes": dtos["nodes"],
        "edges": dtos["edges"],
        "truncated": truncated,
        "counts": {"nodes": len(nodes), "edges": len(edges)},
    }


def _label_graph_group(group_id: str) -> dict[str, str]:
    """One Graph-tab selector entry: ``{id, label, kind}``. Both the **logical label** and the
    **kind** come from the firm group-ID policy (group_scope) so naming is defined in one place
    (docs/graph-group-policy-design.md §4) — knowledge/memory/eval render as logical names, not
    raw ids; legacy/unknown ids fall back to the raw id so they stay selectable/removable."""
    from hirocli.services.knowledge.graph.group_scope import classify_group, group_label

    return {"id": group_id, "label": group_label(group_id), "kind": classify_group(group_id)}


async def graph_groups_payload(workspace_path: Path) -> dict[str, Any]:
    """List the graph's partitions for the admin Graph tab's group selector.

    Returns ``{"default_group_id", "groups": [{id, label, kind}]}`` — "Knowledge" first,
    then conversation-memory groups, then any others. Empty when no graph is built yet.
    """
    group_ids, default_gid = await read_graph_group_ids(graphiti_db_path(workspace_path))
    labeled = [_label_graph_group(g) for g in group_ids]
    # Stable, friendly order: knowledge first, then memory, then eval, then other — each
    # alphabetical.
    kind_rank = {"knowledge": 0, "memory": 1, "eval": 2, "other": 3}
    labeled.sort(key=lambda g: (kind_rank.get(g["kind"], 9), g["label"].lower()))
    return {"default_group_id": default_gid, "groups": labeled}


async def _gather_episodes(
    service: KnowledgeService, document_id: str
) -> tuple[list[GraphitiEpisodeInput], str | None]:
    """Walk all pages of a document's chunks → episodes. Returns (episodes, title)."""
    episodes: list[GraphitiEpisodeInput] = []
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
            episodes.append(
                GraphitiEpisodeInput(
                    chunk_id=point_id,
                    document_id=document_id,
                    text=text,
                    document_title=title or "",
                )
            )
        offset = detail.chunk_next_offset
        if not offset:
            break
    return episodes, title


def _empty_totals() -> dict[str, int]:
    return {
        "episodes_processed": 0,
        "episodes_rejected": 0,
        "episodes_failed": 0,
        "entities_total": 0,
        "edges_total": 0,
    }


def _fold_into_totals(totals: dict[str, int], stats: dict[str, Any]) -> None:
    for key in totals:
        value = stats.get(key)
        if isinstance(value, (int, float)):
            totals[key] += int(value)


async def _run_graph_ingest_for_documents(
    service: KnowledgeService,
    workspace_path: Path,
    document_ids: list[str],
    *,
    source_role: str,
    on_progress: Any | None = None,
    event_sink: GraphEventSink | None = None,
) -> dict[str, Any]:
    """Shared helper for the single + batch graph-ingest tools.

    Builds ONE :class:`GraphitiMemoryService` (model tiers + shared embedder + Kuzu)
    and initializes it once, then iterates documents — so a batch pays one setup
    cost, not N. Per-document failures are **isolated**: a bad doc is marked
    ``ok=False`` with its error and the batch continues.

    ``on_progress`` fires after each document (Phase 5c live UI). ``event_sink``
    (HTTP layer) makes ingest emit live progress events for the Graph tab.
    """
    if not document_ids:
        return {"document_count": 0, "documents": [], "totals": _empty_totals()}

    prefs = load_preferences(workspace_path)
    # require_backend=False: an explicit build-graph action ingests even when the
    # retrieval backend toggle is off (build now, enable retrieval later).
    svc = GraphitiMemoryService.from_preferences(
        prefs, workspace_path, require_backend=False
    )
    if svc is None:
        raise RuntimeError(
            "knowledge_graph_ingest: no extraction model configured. Set "
            "knowledge.graph.extraction_model or knowledge.answering.model (or "
            "llm.default_chat) and ensure the provider key is configured."
        )

    # One ledger run per document (per ingest_chunks call) → each document's graph
    # build is drillable in Graph Runs with per-operation step detail.
    ledger_sink = LedgerSink(workspace_path)
    per_doc: list[dict[str, Any]] = []
    totals = _empty_totals()
    try:
        await svc.initialize()
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
                episodes, title = await _gather_episodes(service, document_id)
                entry["document_title"] = title or ""
                log.info(
                    "⬇️ graphiti.ingest — %d episode(s) from document · doc_id=%s title=%r",
                    len(episodes),
                    document_id,
                    title or "",
                )
                stats = await svc.ingest_chunks(
                    episodes,
                    source_role=source_role,
                    event_sink=event_sink,
                    ledger_sink=ledger_sink,
                )
                stats_dict = stats.as_dict()
                entry["ok"] = True
                entry["stats"] = stats_dict
                _fold_into_totals(totals, stats_dict)
            except Exception as exc:
                # Per-doc failure isolation. Log + record + continue.
                log.warning(
                    "⚠️ graphiti.ingest — document failed · doc_id=%s · %s",
                    document_id,
                    str(exc)[:200],
                    exc_info=True,
                )
                entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            per_doc.append(entry)
            if on_progress is not None:
                try:
                    on_progress(dict(entry))
                except Exception:
                    log.exception("⚠️ graphiti.ingest — on_progress callback failed")
    finally:
        await svc.close()

    return {
        "document_count": len(document_ids),
        "documents": per_doc,
        "totals": totals,
    }


def _open_graph_service_for_teardown(workspace_path: Path) -> GraphitiMemoryService:
    """Build the graph service for a delete/clear op (no retrieval-backend gate).

    Teardown still needs the full service (Kuzu driver + graphiti client) to page
    episodes and remove their nodes/edges. ``require_backend=False`` so a wipe works
    even when the retrieval toggle is off. Raises a clear error when no extraction model
    is configured (a graph can't exist without one having built it)."""
    prefs = load_preferences(workspace_path)
    svc = GraphitiMemoryService.from_preferences(
        prefs, workspace_path, require_backend=False
    )
    if svc is None:
        raise RuntimeError(
            "knowledge graph teardown: no extraction model configured. Set "
            "knowledge.graph.extraction_model or knowledge.answering.model (or "
            "llm.default_chat) and ensure the provider key is configured."
        )
    return svc


async def clear_knowledge_graph(workspace_path: Path) -> int:
    """Delete the ENTIRE knowledge graph (all entities + facts) for this workspace.

    Wipes every episode in the knowledge default group; Qdrant chunks/documents are
    untouched so the graph can be rebuilt from them. Idempotent — an empty graph
    removes 0. Backs the admin Graph tab's "Clear graph" action."""
    svc = _open_graph_service_for_teardown(workspace_path)
    try:
        await svc.initialize()
        group_id = svc.group_id
        if not group_id:
            return 0
        removed = await svc.clear_group(group_id)
        log.info("🧹 knowledge graph cleared · group=%s episodes=%d", group_id, removed)
        return removed
    finally:
        await svc.close()


async def remove_document_from_graph(workspace_path: Path, document_id: str) -> int:
    """Delete one document's episodes (+ the entities/facts they exclusively own) from
    the knowledge graph, keeping its Qdrant chunks. Idempotent — a missing/blank
    document removes 0. Closes the orphan-on-document-delete gap and backs the Browse
    tab's per-document "Remove from graph" action."""
    did = (document_id or "").strip()
    if not did:
        return 0
    svc = _open_graph_service_for_teardown(workspace_path)
    try:
        await svc.initialize()
        removed = await svc.remove_episodes_by_document(did)
        log.info(
            "🧹 knowledge graph — document removed · doc_id=%s episodes=%d", did, removed
        )
        return removed
    finally:
        await svc.close()


class KnowledgeGraphIngestTool(Tool):
    """Build the Graphiti temporal graph for a previously-ingested document.

    Reads the document's chunks from Qdrant (via the knowledge service) and
    ingests them as Graphiti episodes (``uuid = point_id``). Idempotent: Graphiti
    dedupes by episode uuid, so re-running merges rather than duplicates.

    For multiple documents in one call, use ``knowledge_graph_ingest_batch`` — it
    pays the model/graph setup cost once instead of N times.
    """

    runtime = True
    name = "knowledge_graph_ingest"
    description = (
        "Build the Graphiti temporal knowledge graph from a knowledge document's "
        "chunks (one episode per chunk). Idempotent; pairs with the Qdrant evidence pipeline."
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
    """Batch variant of ``knowledge_graph_ingest`` — pays the model/graph setup
    cost ONCE for N documents instead of N times.

    Used by the Ingest tab's "Also build graph" checkbox and the Eval Batch setup.
    Per-document failures are isolated; idempotent re-run (Graphiti dedupes by uuid).
    """

    runtime = True
    name = "knowledge_graph_ingest_batch"
    description = (
        "Graph-ingest N already-ingested documents in one call (Graphiti). "
        "Per-doc failure isolation; idempotent re-run."
    )
    params = {
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
    """Export the whole knowledge graph (nodes + edges) for the admin Graph tab.

    Read-only load path. Phase 4 implements the real Kuzu snapshot; for now it
    returns an empty graph (no DB side effect). See docs/knowledge-graphiti-pivot-design.md.
    """

    runtime = True
    name = "knowledge_graph_export"
    description = (
        "Export the whole knowledge graph (nodes + edges) as JSON for "
        "visualization. Read-only; empty graph until the Phase 4 snapshot lands."
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
        return await graph_snapshot_payload(
            workspace_path, node_limit=node_limit, edge_limit=edge_limit
        )


__all__ = [
    "KnowledgeGraphExportTool",
    "KnowledgeGraphIngestBatchTool",
    "KnowledgeGraphIngestTool",
    "graph_snapshot_payload",
]
