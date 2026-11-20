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
from hirocli.runtime.agent_graph.workspace_ledger import workspace_ledger_sink
from ..services.knowledge import KnowledgeService, create_knowledge_service
from ..services.knowledge.graph_factory import build_graph_service, graph_query_timeout
from hiro_memory.graph import GraphitiMemoryService
from hiro_memory.graph.graphiti_ingest import GraphEventSink
from hiro_memory.graph.views import graph_snapshot_payload
from hiro_memory.knowledge.graph_build import (
    build_document_graph,
    empty_graph_totals,
    remove_document_episodes,
)
from .base import Tool, ToolParam

log = Logger.get("SVC.KNOWLEDGE.GRAPH.TOOL")


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
        return {"document_count": 0, "documents": [], "totals": empty_graph_totals()}

    prefs = load_preferences(workspace_path)
    # require_backend=False: an explicit build-graph action ingests even when the
    # retrieval backend toggle is off (build now, enable retrieval later).
    svc = build_graph_service(
        prefs, workspace_path, require_backend=False
    )
    if svc is None:
        raise RuntimeError(
            "knowledge_graph_ingest: no extraction model configured. Pick an AI profile for "
            "graph.extraction_profile (or Hiro's chat, llm.chat_profile) and make sure its "
            "provider key is configured."
        )

    # One ledger run per document (per ingest_chunks call) → each document's graph
    # build is drillable in Graph Runs with per-operation step detail.
    try:
        return await build_document_graph(
            svc,
            service,
            document_ids,
            source_role=source_role,
            ledger_sink=workspace_ledger_sink(workspace_path),
            on_progress=on_progress,
            event_sink=event_sink,
        )
    finally:
        await svc.close()


def _open_graph_service_for_teardown(workspace_path: Path) -> GraphitiMemoryService:
    """Build the graph service for a delete/clear op (no retrieval-backend gate).

    Teardown still needs the full service (Kuzu driver + graphiti client) to page
    episodes and remove their nodes/edges. ``require_backend=False`` so a wipe works
    even when the retrieval toggle is off. Raises a clear error when no extraction model
    is configured (a graph can't exist without one having built it)."""
    prefs = load_preferences(workspace_path)
    svc = build_graph_service(
        prefs, workspace_path, require_backend=False
    )
    if svc is None:
        raise RuntimeError(
            "knowledge graph teardown: no extraction model configured. Pick an AI profile for "
            "graph.extraction_profile (or Hiro's chat, llm.chat_profile) and make sure its "
            "provider key is configured."
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
        return await remove_document_episodes(svc, did)
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
                "stats": doc.get("stats") or empty_graph_totals(),
                "ok": doc.get("ok", False),
                "error": doc.get("error", ""),
            }
        finally:
            if owned:
                await service.close()


class KnowledgeGraphIngestBatchTool(Tool):
    """Batch variant of ``knowledge_graph_ingest`` — pays the model/graph setup
    cost ONCE for N documents instead of N times.

    Used by the Ingest tab's "Also build graph" checkbox.
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

    async def execute_async(self, **kwargs: Any) -> Any:
        """The logging plan's phase 6a: one graph_ingest is a named story (KNOWLEDGE step `graph.ingest`), under the
        admin request that asked, or of its own from the CLI."""
        from ..runtime import stories

        with stories.started(stories.GRAPH_INGEST, "graph.ingest", title=f"{len(kwargs.get('document_ids') or [])} documents", area="KNOWLEDGE"):
            return await self._execute_async(**kwargs)

    async def _execute_async(
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
            workspace_path,
            node_limit=node_limit,
            edge_limit=edge_limit,
            query_timeout_s=graph_query_timeout(workspace_path),
        )


__all__ = [
    "KnowledgeGraphExportTool",
    "KnowledgeGraphIngestBatchTool",
    "KnowledgeGraphIngestTool",
]
