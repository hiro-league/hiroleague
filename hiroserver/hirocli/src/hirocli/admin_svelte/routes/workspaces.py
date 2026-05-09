"""Workspace admin routes (largest handler count on the Svelte admin API)."""

from __future__ import annotations

from functools import partial
from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from hirocli.admin.features.workspaces.service import WorkspaceService
from hirocli.admin_svelte.result_payload import _api_from_result
from hirocli.admin_svelte.workspace_ctx import _hosting_workspace_id
from hirocli.admin_svelte.schemas import (
    OpenFolderRequest,
    WorkspaceCreateRequest,
    WorkspaceRemoveRequest,
    WorkspaceRestartRequest,
    WorkspaceSetupRequest,
    WorkspaceUpdateRequest,
)

workspaces_router = APIRouter()


@workspaces_router.get("/workspaces")
async def list_workspaces() -> dict[str, Any]:
    """Return workspace rows for the admin UI."""
    hosting_workspace_id = _hosting_workspace_id()
    result = await run_in_threadpool(WorkspaceService().list_rows, hosting_workspace_id)
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    payload["hosting_workspace_id"] = hosting_workspace_id
    return payload


@workspaces_router.post("/workspaces")
async def create_workspace(body: WorkspaceCreateRequest) -> dict[str, Any]:
    result = await run_in_threadpool(WorkspaceService().create, body.name, body.path)
    return _api_from_result(result)


@workspaces_router.patch("/workspaces/{workspace_id}")
async def update_workspace(workspace_id: str, body: WorkspaceUpdateRequest) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(
            WorkspaceService().update,
            workspace_id,
            name=body.name,
            gateway_url=body.gateway_url,
            set_default=body.set_default,
            previous_display_name=body.previous_display_name,
        )
    )
    return _api_from_result(result)


@workspaces_router.delete("/workspaces/{workspace_id}")
async def remove_workspace(workspace_id: str, body: WorkspaceRemoveRequest) -> dict[str, Any]:
    result = await run_in_threadpool(
        WorkspaceService().remove,
        workspace_id,
        body.purge,
        _hosting_workspace_id(),
    )
    return _api_from_result(result)


@workspaces_router.post("/workspaces/{workspace_id}/start")
async def start_workspace(workspace_id: str) -> dict[str, Any]:
    result = await run_in_threadpool(WorkspaceService().start, workspace_id)
    if not result.ok or result.data is None:
        return _api_from_result(result)
    name, already_running, pid = result.data
    return {
        "ok": True,
        "error": None,
        "data": {"name": name, "already_running": already_running, "pid": pid},
    }


@workspaces_router.post("/workspaces/{workspace_id}/stop")
async def stop_workspace(workspace_id: str) -> dict[str, Any]:
    result = await run_in_threadpool(
        WorkspaceService().stop,
        workspace_id,
        _hosting_workspace_id(),
    )
    return _api_from_result(result)


@workspaces_router.post("/workspaces/{workspace_id}/restart")
async def restart_workspace(workspace_id: str, body: WorkspaceRestartRequest) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(WorkspaceService().restart, workspace_id, admin=body.admin)
    )
    return _api_from_result(result)


@workspaces_router.post("/workspaces/{workspace_id}/setup")
async def setup_workspace(workspace_id: str, body: WorkspaceSetupRequest) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(
            WorkspaceService().setup,
            workspace_id,
            gateway_url=body.gateway_url,
            http_port=body.http_port,
            skip_autostart=body.skip_autostart,
            start_server=body.start_server,
            elevated_task=body.elevated_task,
        )
    )
    if not result.ok or result.data is None:
        return _api_from_result(result)
    setup_result = result.data
    return {
        "ok": True,
        "error": None,
        "data": {
            "workspace": getattr(setup_result, "workspace", ""),
            "desktop_pub": getattr(setup_result, "desktop_pub", ""),
        },
    }


@workspaces_router.get("/workspaces/{workspace_id}/public-key")
async def get_workspace_public_key(workspace_id: str) -> dict[str, Any]:
    result = await run_in_threadpool(WorkspaceService().get_public_key, workspace_id)
    return _api_from_result(result)


@workspaces_router.post("/workspaces/{workspace_id}/regenerate-key")
async def regenerate_workspace_key(workspace_id: str) -> dict[str, Any]:
    result = await run_in_threadpool(WorkspaceService().regenerate_key, workspace_id)
    return _api_from_result(result)


@workspaces_router.post("/workspaces/open-folder")
async def open_workspace_folder(body: OpenFolderRequest) -> dict[str, Any]:
    result = await run_in_threadpool(WorkspaceService().open_folder, body.path)
    return _api_from_result(result)


@workspaces_router.post("/open-path")
async def open_path(body: OpenFolderRequest) -> dict[str, Any]:
    result = await run_in_threadpool(WorkspaceService().open_folder, body.path)
    return _api_from_result(result)
