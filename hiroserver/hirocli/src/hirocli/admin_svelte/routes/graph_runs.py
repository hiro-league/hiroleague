"""Graph execution ledger admin routes.

A run's per-stage traces (``/graph-runs/{run_id}/retrieval-trace`` and ``/ingest-trace``), which the UI kit's trace
dialogs read, are the memory library's routes (``hiro_memory.routes.trace_routes``), mounted here over the selected
workspace.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from hiro_memory.routes import trace_routes
from starlette.concurrency import run_in_threadpool

from hirocli.admin.features.graph_runs.service import GraphLedgerService, langsmith_url_for_run
from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import _api_data
from hirocli.admin_svelte.schemas import GraphRunsTailRequest
from hirocli.domain.workspace import resolve_workspace

graph_runs_router = APIRouter()


def _selected_workspace(workspace_id: SelectedWorkspaceIdDep) -> Path:
    entry, _ = resolve_workspace(workspace_id)
    return Path(entry.path).resolve()


graph_runs_router.include_router(trace_routes(workspace=_selected_workspace))


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


@graph_runs_router.get("/graph-runs/{run_id}/retrieval-loop")
async def get_graph_run_retrieval_loop(
    run_id: str,
    workspace_id: SelectedWorkspaceIdDep,
) -> Any:
    """Full retrieval-recall detail for a chat recall run, read live from the agent sidecars: the loop
    trajectory (``loop``) plus the recalled facts/entities/episodes (``recalled``), draft ``answer``,
    and ``render`` caps — what Graph Runs' recall detail dialog renders. All null/empty when tracing
    wasn't enabled for the run."""
    result = await run_in_threadpool(
        GraphLedgerService().retrieval_loop,
        workspace_id,
        run_id,
    )
    if not result.ok:
        return _api_data(result)
    return result.data or {"loop": None, "recalled": [], "answer": "", "render": None}


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
