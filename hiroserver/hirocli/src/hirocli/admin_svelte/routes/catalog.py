"""LLM catalog browser routes (bundled catalog.yaml)."""

from __future__ import annotations

from functools import partial
from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from hirocli.admin.features.catalog.service import CatalogBrowserService
from hirocli.admin_svelte.result_payload import _api_from_result

catalog_router = APIRouter()


@catalog_router.get("/catalog/providers")
async def list_catalog_providers(hosting: str | None = None) -> dict[str, Any]:
    result = await run_in_threadpool(CatalogBrowserService().list_providers, hosting)
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
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


@catalog_router.post("/catalog/reload")
async def reload_catalog() -> dict[str, Any]:
    """Clear in-process catalog cache and reload bundled ``catalog.yaml``."""
    result = await run_in_threadpool(CatalogBrowserService().reload_from_disk)
    return _api_from_result(result)
