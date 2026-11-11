"""Graph execution ledger admin routes."""

from __future__ import annotations

from functools import partial
from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from hirocli.admin.features.graph_runs.service import GraphLedgerService, langsmith_url_for_run
from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import _api_data
from hirocli.admin_svelte.schemas import GraphRunsTailRequest

graph_runs_router = APIRouter()


@graph_runs_router.post("/graph-runs/tail")
async def tail_graph_runs(
    body: GraphRunsTailRequest,
    workspace_id: SelectedWorkspaceIdDep,
) -> Any:
    service = GraphLedgerService()
    if body.after_offsets:
        result = await run_in_threadpool(
            partial(
                service.tail_after_offsets,
                workspace_id,
                body.after_offsets,
                filters=body.filters,
            )
        )
    else:
        result = await run_in_threadpool(
            partial(
                service.tail_initial,
                workspace_id,
                lines=body.lines or 100,
                since_seconds_ago=body.since_seconds_ago,
                skip_from_end=body.skip_from_end or 0,
                filters=body.filters,
            )
        )
    if not result.ok or result.data is None:
        return _api_data(result)
    return {
            "rows": result.data.rows,
            "file_offsets": result.data.file_offsets,
            "has_more": result.data.has_more,
        }


@graph_runs_router.get("/graph-runs/{run_id}/langsmith-url")
async def get_graph_run_langsmith_url(
    run_id: str,
    workspace_id: SelectedWorkspaceIdDep,
) -> Any:
    """Resolve LangSmith trace URL (may call LangSmith API — keep off the inspect path so node rows load fast)."""
    _ = workspace_id
    url = await run_in_threadpool(langsmith_url_for_run, run_id)
    return {"langsmith_url": url}


@graph_runs_router.get("/graph-runs/{run_id}/retrieval-trace")
async def get_graph_run_retrieval_trace(
    run_id: str,
    workspace_id: SelectedWorkspaceIdDep,
) -> Any:
    """Per-stage Graphiti fact-search traces for a run (candidate legs / hop / rank /
    temporal). Empty list when tracing wasn't enabled for the run."""
    result = await run_in_threadpool(
        GraphLedgerService().retrieval_trace,
        workspace_id,
        run_id,
    )
    if not result.ok or result.data is None:
        return _api_data(result)
    return {"traces": result.data}


@graph_runs_router.get("/graph-runs/{run_id}/retrieval-loop")
async def get_graph_run_retrieval_loop(
    run_id: str,
    workspace_id: SelectedWorkspaceIdDep,
) -> Any:
    """Full retrieval-recall detail for a chat recall run, read live from the agent sidecars: the loop
    trajectory (``loop``) plus the recalled facts/entities/episodes (``recalled``), draft ``answer``,
    and ``render`` caps — the same shape the eval detail dialog renders. All null/empty when tracing
    wasn't enabled for the run."""
    result = await run_in_threadpool(
        GraphLedgerService().retrieval_loop,
        workspace_id,
        run_id,
    )
    if not result.ok:
        return _api_data(result)
    return result.data or {"loop": None, "recalled": [], "answer": "", "render": None}


@graph_runs_router.get("/graph-runs/{run_id}/ingest-trace")
async def get_graph_run_ingest_trace(
    run_id: str,
    workspace_id: SelectedWorkspaceIdDep,
) -> Any:
    """Per-stage Graphiti ``add_episode`` traces for a run (extract → resolve → facts →
    dates → fact-resolution → summarize, plus the persisted result). Empty list when
    tracing wasn't enabled for the run."""
    result = await run_in_threadpool(
        GraphLedgerService().ingest_trace,
        workspace_id,
        run_id,
    )
    if not result.ok or result.data is None:
        return _api_data(result)
    return {"traces": result.data}


@graph_runs_router.get("/graph-runs/{run_id}")
async def get_graph_run(
    run_id: str,
    workspace_id: SelectedWorkspaceIdDep,
) -> Any:
    result = await run_in_threadpool(
        GraphLedgerService().inspect_run,
        workspace_id,
        run_id,
    )
    if not result.ok or result.data is None:
        return _api_data(result)
    snapshot = result.data
    return {
            "rows": snapshot.timeline,
            "aggregate": snapshot.aggregate_row,
        }
