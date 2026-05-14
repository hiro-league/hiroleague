"""Graph execution ledger admin routes."""

from __future__ import annotations

from functools import partial
from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from hirocli.admin.features.graph_runs.service import GraphLedgerService, langsmith_url_for_run
from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import _api_from_result
from hirocli.admin_svelte.schemas import GraphRunsTailRequest

graph_runs_router = APIRouter()


@graph_runs_router.post("/graph-runs/tail")
async def tail_graph_runs(
    body: GraphRunsTailRequest,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
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
                lines=body.lines or 500,
                since_seconds_ago=body.since_seconds_ago,
                filters=body.filters,
            )
        )
    if not result.ok or result.data is None:
        return _api_from_result(result)
    return {
        "ok": True,
        "error": None,
        "data": {
            "rows": result.data.rows,
            "file_offsets": result.data.file_offsets,
        },
    }


@graph_runs_router.get("/graph-runs/{run_id}")
async def get_graph_run(
    run_id: str,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    result = await run_in_threadpool(
        GraphLedgerService().inspect_run,
        workspace_id,
        run_id,
    )
    if not result.ok or result.data is None:
        return _api_from_result(result)
    snapshot = result.data
    langsmith_url = await run_in_threadpool(langsmith_url_for_run, run_id)
    return {
        "ok": True,
        "error": None,
        "data": {
            "rows": snapshot.timeline,
            "aggregate": snapshot.aggregate_row,
            "langsmith_url": langsmith_url,
        },
    }
