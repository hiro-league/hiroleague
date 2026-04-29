"""FastAPI routes for the Svelte-based HiroAdmin.

Routes call existing admin services rather than duplicating business logic. This
keeps the Svelte migration aligned with the current NiceGUI admin while making
the frontend/backend boundary explicit.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from fastapi import APIRouter, Header
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from hirocli.admin.context import get_runtime_context
from hirocli.admin.features.catalog.service import CatalogBrowserService
from hirocli.admin.features.gateways.service import GatewayService
from hirocli.admin.features.providers.service import ProvidersPageService
from hirocli.admin.features.workspaces.service import WorkspaceService
from hirocli.admin.shared.result import Result
from hirocli.admin_svelte.static_server import ADMIN_NEXT_PATH

api_router = APIRouter(prefix=f"{ADMIN_NEXT_PATH}/api", tags=["hiro-admin-next"])


class ApiResponse(BaseModel):
    ok: bool
    error: str | None = None
    data: Any = None


class WorkspaceListResponse(ApiResponse):
    hosting_workspace_id: str | None = None


class WorkspaceCreateRequest(BaseModel):
    name: str
    path: str | None = None


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = None
    gateway_url: str | None = None
    set_default: bool = False
    previous_display_name: str = ""


class WorkspaceRemoveRequest(BaseModel):
    purge: bool = False


class WorkspaceRestartRequest(BaseModel):
    admin: bool = False


class WorkspaceSetupRequest(BaseModel):
    gateway_url: str
    http_port: int | None = None
    skip_autostart: bool = False
    start_server: bool = False
    elevated_task: bool = False


class OpenFolderRequest(BaseModel):
    path: str


class GatewayCreateRequest(BaseModel):
    name: str
    desktop_public_key: str
    port: int
    host: str = "0.0.0.0"
    log_dir: str = ""
    make_default: bool = False
    skip_autostart: bool = False
    elevated_task: bool = False


class GatewayStartRequest(BaseModel):
    verbose: bool = False


class GatewayRemoveRequest(BaseModel):
    purge: bool = False
    elevated_task: bool = False


class ProviderAddApiKeyRequest(BaseModel):
    provider_id: str
    api_key: str


def _hosting_workspace_id() -> str | None:
    ctx = get_runtime_context()
    return ctx.hosting_workspace_id if ctx else None


def _selected_workspace_id(header_workspace_id: str | None) -> str | None:
    selected = (header_workspace_id or "").strip()
    return selected or _hosting_workspace_id()


def _api_from_result(result: Result[Any]) -> dict[str, Any]:
    if not result.ok:
        return {"ok": False, "error": result.error or "Operation failed.", "data": None}
    return {"ok": True, "error": None, "data": result.data}


@api_router.get("/workspaces")
async def list_workspaces() -> dict[str, Any]:
    """Return workspace rows using the same service as the NiceGUI admin page."""
    hosting_workspace_id = _hosting_workspace_id()
    result = await run_in_threadpool(WorkspaceService().list_rows, hosting_workspace_id)
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    payload["hosting_workspace_id"] = hosting_workspace_id
    return payload


@api_router.post("/workspaces")
async def create_workspace(body: WorkspaceCreateRequest) -> dict[str, Any]:
    result = await run_in_threadpool(WorkspaceService().create, body.name, body.path)
    return _api_from_result(result)


@api_router.patch("/workspaces/{workspace_id}")
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


@api_router.delete("/workspaces/{workspace_id}")
async def remove_workspace(workspace_id: str, body: WorkspaceRemoveRequest) -> dict[str, Any]:
    result = await run_in_threadpool(
        WorkspaceService().remove,
        workspace_id,
        body.purge,
        _hosting_workspace_id(),
    )
    return _api_from_result(result)


@api_router.post("/workspaces/{workspace_id}/start")
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


@api_router.post("/workspaces/{workspace_id}/stop")
async def stop_workspace(workspace_id: str) -> dict[str, Any]:
    result = await run_in_threadpool(
        WorkspaceService().stop,
        workspace_id,
        _hosting_workspace_id(),
    )
    return _api_from_result(result)


@api_router.post("/workspaces/{workspace_id}/restart")
async def restart_workspace(workspace_id: str, body: WorkspaceRestartRequest) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(WorkspaceService().restart, workspace_id, admin=body.admin)
    )
    return _api_from_result(result)


@api_router.post("/workspaces/{workspace_id}/setup")
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


@api_router.get("/workspaces/{workspace_id}/public-key")
async def get_workspace_public_key(workspace_id: str) -> dict[str, Any]:
    result = await run_in_threadpool(WorkspaceService().get_public_key, workspace_id)
    return _api_from_result(result)


@api_router.post("/workspaces/{workspace_id}/regenerate-key")
async def regenerate_workspace_key(workspace_id: str) -> dict[str, Any]:
    result = await run_in_threadpool(WorkspaceService().regenerate_key, workspace_id)
    return _api_from_result(result)


@api_router.post("/workspaces/open-folder")
async def open_workspace_folder(body: OpenFolderRequest) -> dict[str, Any]:
    result = await run_in_threadpool(WorkspaceService().open_folder, body.path)
    return _api_from_result(result)


@api_router.get("/gateways")
async def list_gateways() -> dict[str, Any]:
    result = await run_in_threadpool(GatewayService().list_instances)
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    return payload


@api_router.get("/catalog/providers")
async def list_catalog_providers(hosting: str | None = None) -> dict[str, Any]:
    result = await run_in_threadpool(CatalogBrowserService().list_providers, hosting)
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    return payload


@api_router.get("/catalog/models")
async def list_catalog_models(
    provider_id: str | None = None,
    model_kind: str | None = None,
    model_class: str | None = None,
    hosting: str | None = None,
) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(
            CatalogBrowserService().list_models,
            provider_id=provider_id,
            model_kind=model_kind,
            model_class=model_class,
            hosting=hosting,
        )
    )
    if not result.ok or result.data is None:
        return _api_from_result(result)
    catalog_version, models = result.data
    return {
        "ok": True,
        "error": None,
        "data": {"catalog_version": catalog_version, "models": models},
    }


@api_router.get("/providers")
async def list_active_providers(
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().list_configured,
        _selected_workspace_id(x_hiro_workspace),
    )
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    return payload


@api_router.get("/providers/addable")
async def list_addable_providers(
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().list_addable_cloud_providers,
        _selected_workspace_id(x_hiro_workspace),
    )
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    return payload


@api_router.post("/providers")
async def add_provider_api_key(
    body: ProviderAddApiKeyRequest,
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().add_api_key,
        _selected_workspace_id(x_hiro_workspace),
        body.provider_id,
        body.api_key,
    )
    return _api_from_result(result)


@api_router.post("/providers/scan-env")
async def scan_provider_environment(
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().scan_environment_for_keys,
        _selected_workspace_id(x_hiro_workspace),
    )
    return _api_from_result(result)


@api_router.delete("/providers/{provider_id}")
async def remove_provider(
    provider_id: str,
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().remove_provider,
        _selected_workspace_id(x_hiro_workspace),
        provider_id,
    )
    return _api_from_result(result)


@api_router.post("/gateways")
async def create_gateway(body: GatewayCreateRequest) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(
            GatewayService().setup_instance,
            name=body.name,
            desktop_public_key=body.desktop_public_key,
            port=body.port,
            host=body.host,
            log_dir=body.log_dir,
            make_default=body.make_default,
            skip_autostart=body.skip_autostart,
            elevated_task=body.elevated_task,
        )
    )
    return _api_from_result(result)


@api_router.post("/gateways/{instance_name}/start")
async def start_gateway(instance_name: str, body: GatewayStartRequest) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(GatewayService().start, instance_name, verbose=body.verbose)
    )
    if not result.ok or result.data is None:
        return _api_from_result(result)
    already_running, pid = result.data
    return {
        "ok": True,
        "error": None,
        "data": {"already_running": already_running, "pid": pid},
    }


@api_router.post("/gateways/{instance_name}/stop")
async def stop_gateway(instance_name: str) -> dict[str, Any]:
    result = await run_in_threadpool(GatewayService().stop, instance_name)
    return _api_from_result(result)


@api_router.delete("/gateways/{instance_name}")
async def remove_gateway(instance_name: str, body: GatewayRemoveRequest) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(
            GatewayService().teardown_instance,
            instance_name,
            purge=body.purge,
            elevated_task=body.elevated_task,
        )
    )
    return _api_from_result(result)


def include_admin_svelte_api(app: Any) -> None:
    """Attach Svelte admin API routes to the admin FastAPI app."""
    app.include_router(api_router)
