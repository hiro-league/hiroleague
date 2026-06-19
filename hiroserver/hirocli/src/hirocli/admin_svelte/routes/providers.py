"""Active provider configuration routes (workspace-scoped)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from hirocli.admin.features.providers.service import ProvidersPageService
from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import _api_from_result
from hirocli.admin_svelte.schemas import (
    ProviderAddApiKeyRequest,
    ProviderCheckRequest,
    ProviderSetEndpointRequest,
)
from hirocli.domain.local_models import (
    LOCAL_PROVIDER_ID,
    list_local_model_rows,
    list_local_providers,
)
from hirocli.domain.workspace import resolve_workspace

providers_router = APIRouter()


def _local_active_provider(workspace_id: str | None) -> dict[str, Any]:
    """The local in-process provider as an always-available (no-key) active-provider row."""
    prov = list_local_providers()[0]
    entry, _ = resolve_workspace(workspace_id)
    rows = list_local_model_rows(Path(entry.path))
    kinds = {r.model_kind for r in rows}
    return {
        "provider_id": prov.id,
        "display_name": prov.display_name,
        "hosting": prov.hosting,
        "auth_method": "local",  # no credential — always available
        "available_model_count": len(rows),
        "has_chat": False,
        "has_tts": False,
        "has_stt": False,
        "has_embedding": "embedding" in kinds,
        "has_rerank": "rerank" in kinds,
        "has_image_gen": False,
    }


@providers_router.get("/providers")
async def list_active_providers(workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().list_configured,
        workspace_id,
    )
    payload = _api_from_result(result)
    data = list(payload["data"] or [])
    data.append(await run_in_threadpool(_local_active_provider, workspace_id))
    payload["data"] = data
    return payload


@providers_router.get("/providers/addable")
async def list_addable_providers(workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().list_addable_providers,
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
        body.account_id,
    )
    return _api_from_result(result)


@providers_router.post("/providers/local")
async def set_provider_local_endpoint(
    body: ProviderSetEndpointRequest,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().set_local_endpoint,
        workspace_id,
        body.provider_id,
        body.base_url,
    )
    return _api_from_result(result)


@providers_router.post("/providers/check")
async def check_provider_endpoint(
    body: ProviderCheckRequest,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().check_endpoint,
        workspace_id,
        body.provider_id,
        body.base_url,
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
