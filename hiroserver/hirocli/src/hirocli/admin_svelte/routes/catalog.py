"""LLM catalog browser routes (bundled catalog.yaml)."""

from __future__ import annotations

import dataclasses
from functools import partial
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from hirocli.admin.features.catalog.service import CatalogBrowserService
from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import _api_from_result, envelope_failure
from hirocli.domain.local_models import list_local_model_rows, list_local_providers
from hirocli.domain.workspace import resolve_workspace

catalog_router = APIRouter()


@catalog_router.get("/catalog/providers")
async def list_catalog_providers(hosting: str | None = None) -> dict[str, Any]:
    result = await run_in_threadpool(CatalogBrowserService().list_providers, hosting)
    payload = _api_from_result(result)
    data = list(payload["data"] or [])
    # Surface the synthetic local provider so Models rows never reference an invisible provider.
    if hosting in (None, "local"):
        data.extend(dataclasses.asdict(p) for p in list_local_providers())
    payload["data"] = data
    return payload


@catalog_router.get("/catalog/models")
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


@catalog_router.get("/catalog/local-models")
async def list_local_models(
    workspace_id: SelectedWorkspaceIdDep,
    model_kind: str | None = None,
) -> dict[str, Any]:
    """Local in-process downloadable models (read-only browse rows + per-workspace download status).

    Separate from ``/catalog/models`` so the static, workspace-agnostic catalog stays decoupled
    from per-workspace download state. The Catalog browser merges both sources for display.
    """
    try:
        entry, _ = resolve_workspace(workspace_id)
        rows = await run_in_threadpool(
            list_local_model_rows, Path(entry.path), model_kind=model_kind
        )
        return {"ok": True, "error": None, "data": {"models": [dataclasses.asdict(r) for r in rows]}}
    except Exception as exc:
        return envelope_failure(str(exc))


@catalog_router.post("/catalog/reload")
async def reload_catalog() -> dict[str, Any]:
    """Clear in-process catalog cache and reload bundled ``catalog.yaml``."""
    result = await run_in_threadpool(CatalogBrowserService().reload_from_disk)
    return _api_from_result(result)
