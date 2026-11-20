"""Log browsing admin routes."""

from __future__ import annotations

from functools import partial
from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from hirocli.admin.features.logs.service import LogsService
from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.logs_support import _logs_layout, _shape_log_rows
from hirocli.admin_svelte.result_payload import _api_data
from hirocli.admin_svelte.schemas import LogsTailRequest

logs_router = APIRouter()


@logs_router.get("/logs/layout")
async def get_logs_layout(workspace_id: SelectedWorkspaceIdDep) -> Any:
    result = await run_in_threadpool(_logs_layout, workspace_id)
    return _api_data(result)


@logs_router.post("/logs/tail")
async def tail_logs(
    body: LogsTailRequest,
    workspace_id: SelectedWorkspaceIdDep,
) -> Any:
    service = LogsService()
    if body.after_offsets:
        result = await run_in_threadpool(
            service.tail_after_offsets,
            workspace_id,
            body.after_offsets,
        )
    else:
        since = None if body.last_session_only else body.since_seconds_ago
        result = await run_in_threadpool(
            partial(
                service.tail_initial,
                workspace_id,
                lines=body.lines or 500,
                last_session_only=body.last_session_only,
                since_seconds_ago=since,
            )
        )
    if not result.ok or result.data is None:
        return _api_data(result)
    return {
            "rows": _shape_log_rows(result.data.rows, service),
            "file_offsets": result.data.file_offsets,
        }


@logs_router.get("/logs/search")
async def search_logs(
    workspace_id: SelectedWorkspaceIdDep,
    query: str | None = None,
    device_id: str | None = None,
    msg_id: str | None = None,
    method: str | None = None,
    traffic_class: str | None = None,
) -> Any:
    service = LogsService()
    result = await run_in_threadpool(
        service.search_filtered,
        workspace_id,
        query=query,
        device_id=device_id,
        msg_id=msg_id,
        method=method,
        traffic_class=traffic_class,
    )
    if not result.ok:
        return _api_data(result)
    return {"rows": _shape_log_rows(result.data or [], service)}


@logs_router.get("/logs/methods")
async def discover_log_methods(workspace_id: SelectedWorkspaceIdDep) -> Any:
    """Distinct JSON-RPC ``method`` values seen in the recent log tail (scope popup)."""
    service = LogsService()
    result = await run_in_threadpool(
        service.discover_methods,
        workspace_id,
    )
    return _api_data(result)


@logs_router.get("/logs/traffic-classes")
async def list_log_traffic_classes() -> Any:
    """Static enum: the operational traffic_class taxonomy used by comm-path logs."""
    from hiro_channel_sdk.log_scope_fields import TRAFFIC_CLASSES

    return list(TRAFFIC_CLASSES)


@logs_router.post("/logs/clear")
async def clear_logs(workspace_id: SelectedWorkspaceIdDep) -> Any:
    service = LogsService()
    result = await run_in_threadpool(
        service.clear_all,
        workspace_id,
    )
    if not result.ok or result.data is None:
        return _api_data(result)
    return {"cleared_files": result.data.cleared_files}


@logs_router.get("/logs/stories")
async def list_log_stories(
    workspace_id: SelectedWorkspaceIdDep,
    since: str | None = None,
    kind: str | None = None,
    name: str | None = None,
    source: str | None = None,
    problems: bool = False,
    limit: int | None = None,
) -> Any:
    """The named stories of a span across every part (the logging plan's phase 6a)."""
    result = await run_in_threadpool(
        partial(LogsService().stories, workspace_id, since=since, kind=kind, name=name, source=source,
                problems=problems, limit=limit)
    )
    return _api_data(result)


@logs_router.get("/logs/stories/{story_id}")
async def get_log_story(story_id: str, workspace_id: SelectedWorkspaceIdDep) -> Any:
    """One story across every part (the logging plan's phase 6a)."""
    result = await run_in_threadpool(LogsService().story, workspace_id, story_id)
    return _api_data(result)


@logs_router.get("/logs/problems")
async def list_log_problems(workspace_id: SelectedWorkspaceIdDep, since: str | None = None) -> Any:
    """Every part's warnings and errors in a span, grouped (the logging plan's phase 6b)."""
    result = await run_in_threadpool(partial(LogsService().problems, workspace_id, since=since))
    return _api_data(result)
