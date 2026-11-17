"""The graph leg's Graphiti session: the service, its rerank usage and its retrieval trace, closed on exit (P5)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from hiro_memory.graph.ledger_tracer import RerankUsage, current_rerank_usage

if TYPE_CHECKING:
    from hiro_memory.graph.graphiti_service import GraphitiMemoryService


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
        k_hop: int | None = None,
        show_expiry: bool = False,
    ):
        return await self.service.search_chunk_ids(
            query,
            num_results=num_results,
            temporal=temporal,
            k_hop=k_hop,
            show_expiry=show_expiry,
        )


@asynccontextmanager
async def open_graphiti_session(
    service: "GraphitiMemoryService | None",
    *,
    trace: bool,
) -> AsyncIterator[GraphitiSession | None]:
    """Wire the retrieval ContextVars around ``service`` and close it on exit.

    ``service`` is the owner's (the core builds it from its preferences); None yields None (graph backend off or no
    model). ``trace`` turns on the per-stage retrieval capture (the ``trace`` observability tier).
    """
    from hiro_memory.graph.retrieval_trace import RetrievalCapture, current_capture

    if service is None:
        yield None
        return

    rerank_usage = RerankUsage()
    rerank_token = current_rerank_usage.set(rerank_usage)
    capture = RetrievalCapture() if trace else None
    capture_token = current_capture.set(capture) if capture is not None else None
    try:
        yield GraphitiSession(service, rerank_usage, capture)
    finally:
        current_rerank_usage.reset(rerank_token)
        if capture_token is not None:
            current_capture.reset(capture_token)
        await service.close()
