"""FastAPI routes for the Svelte-based Hiro Admin.

Routes call existing admin services rather than duplicating business logic.
Sub-routers live under ``admin_svelte.routes`` (including isolated SSE in ``events``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from hirocli.admin_svelte.routes.catalog import catalog_router
from hirocli.admin_svelte.routes.channels import channels_router
from hirocli.admin_svelte.routes.characters import characters_router
from hirocli.admin_svelte.routes.chat_channels import chat_channels_router
from hirocli.admin_svelte.routes.config import config_router
from hirocli.admin_svelte.routes.devices import devices_router
from hirocli.admin_svelte.routes.events import events_router
from hirocli.admin_svelte.routes.gateways import gateways_router
from hirocli.admin_svelte.routes.logs import logs_router
from hirocli.admin_svelte.routes.metrics import metrics_router
from hirocli.admin_svelte.routes.providers import providers_router
from hirocli.admin_svelte.routes.workspaces import workspaces_router

api_router = APIRouter(prefix="/api", tags=["hiro-admin"])
api_router.include_router(workspaces_router)
api_router.include_router(gateways_router)
api_router.include_router(config_router)
api_router.include_router(catalog_router)
api_router.include_router(providers_router)
api_router.include_router(characters_router)
api_router.include_router(chat_channels_router)
api_router.include_router(channels_router)
api_router.include_router(devices_router)
api_router.include_router(logs_router)
api_router.include_router(metrics_router)
api_router.include_router(events_router)


def include_admin_svelte_api(app: Any) -> None:
    """Attach Svelte admin API routes to the admin FastAPI app."""
    app.include_router(api_router)
