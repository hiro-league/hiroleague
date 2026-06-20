"""Graphiti service lifecycle for knowledge graph_expand (P5)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hirocli.services.knowledge.graph.ledger_tracer import RerankUsage, current_rerank_usage

if TYPE_CHECKING:
    from hirocli.domain.preferences import WorkspacePreferences
    from hirocli.services.knowledge.graph.graphiti_service import GraphitiMemoryService


@dataclass
class GraphitiSession:
    service: "GraphitiMemoryService"
    rerank_usage: RerankUsage
    capture: Any

    async def search_chunk_ids(
        self,
        query: str,
        *,
        num_results: int,
        temporal: str,
    ):
        return await self.service.search_chunk_ids(
            query, num_results=num_results, temporal=temporal
        )


@asynccontextmanager
async def graphiti_session(
    prefs: "WorkspacePreferences",
    workspace_path: Path,
    workspace_id: str | None = None,
):
    """Build GraphitiMemoryService, wire retrieval ContextVars, and close on exit."""
    from hirocli.services.knowledge.graph import GraphitiMemoryService
    from hirocli.services.knowledge.graph.retrieval_trace import (
        RetrievalCapture,
        current_capture,
    )

    service = GraphitiMemoryService.from_preferences(
        prefs, workspace_path, workspace_id=workspace_id
    )
    if service is None:
        yield None
        return

    rerank_usage = RerankUsage()
    rerank_token = current_rerank_usage.set(rerank_usage)
    capture = RetrievalCapture() if prefs.graph.observability == "trace" else None
    capture_token = current_capture.set(capture) if capture is not None else None
    try:
        yield GraphitiSession(service, rerank_usage, capture)
    finally:
        current_rerank_usage.reset(rerank_token)
        if capture_token is not None:
            current_capture.reset(capture_token)
        await service.close()
