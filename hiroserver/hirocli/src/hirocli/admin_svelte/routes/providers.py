"""Active provider configuration routes (workspace-scoped)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from hirocli.admin.features.providers.service import ProvidersPageService
from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import _api_from_result
from hirocli.admin_svelte.schemas import ProviderAddApiKeyRequest

providers_router = APIRouter()


@providers_router.get("/providers")
async def list_active_providers(workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().list_configured,
        workspace_id,
    )
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    return payload


@providers_router.get("/providers/addable")
async def list_addable_providers(workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().list_addable_cloud_providers,
        workspace_id,
    )
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    return payload


@providers_router.post("/providers")
async def add_provider_api_key(
    body: ProviderAddApiKeyRequest,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().add_api_key,
        workspace_id,
        body.provider_id,
        body.api_key,
    )
    return _api_from_result(result)


@providers_router.post("/providers/scan-env")
async def scan_provider_environment(workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().scan_environment_for_keys,
        workspace_id,
    )
    return _api_from_result(result)


@providers_router.delete("/providers/{provider_id}")
async def remove_provider(
    provider_id: str,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().remove_provider,
        workspace_id,
        provider_id,
    )
    return _api_from_result(result)
