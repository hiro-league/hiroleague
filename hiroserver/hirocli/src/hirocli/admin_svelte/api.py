"""FastAPI routes for the Svelte-based Hiro Admin.

Routes call existing admin services rather than duplicating business logic.
Sub-routers live under ``admin_svelte.routes`` (including isolated SSE in ``events``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from hirocli.domain.features import feature_active
from hirocli.admin_svelte.routes.catalog import catalog_router
from hirocli.admin_svelte.routes.channels import channels_router
from hirocli.admin_svelte.routes.characters import characters_router
from hirocli.admin_svelte.routes.chat_channels import chat_channels_router
from hirocli.admin_svelte.routes.config import config_router
from hirocli.admin_svelte.routes.devices import devices_router
from hirocli.admin_svelte.routes.eval import eval_router, eval_shared_router
from hirocli.admin_svelte.routes.events import events_router
from hirocli.admin_svelte.routes.gateways import gateways_router
from hirocli.admin_svelte.routes.graph_runs import graph_runs_router
from hirocli.admin_svelte.routes.image_lab import image_lab_router
from hirocli.admin_svelte.routes.knowledge import knowledge_router, knowledge_shared_router
from hirocli.admin_svelte.routes.logs import logs_router
from hirocli.admin_svelte.routes.memory import memory_router
from hirocli.admin_svelte.routes.metrics import metrics_router
from hirocli.admin_svelte.routes.preferences import preferences_router
from hirocli.admin_svelte.routes.providers import providers_router
from hirocli.admin_svelte.routes.runtime import runtime_router
from hirocli.admin_svelte.routes.workspaces import workspaces_router

api_router = APIRouter(prefix="/api", tags=["hiro-admin"])
api_router.include_router(workspaces_router)
api_router.include_router(gateways_router)
api_router.include_router(graph_runs_router)
# Shared knowledge/eval endpoints (embedder/reranker model mgmt, the graph viewer, the
# `/knowledge/events` SSE, and `/eval/row`) are used by NON-gated features — Settings model pickers,
# the Memories graph tab, and Graph Runs — so they are ALWAYS mounted. See the router split in
# routes/knowledge.py + routes/eval.py.
api_router.include_router(knowledge_shared_router)
api_router.include_router(eval_shared_router)
# Feature-gated: hiding Knowledge / Eval unmounts only their ADMIN endpoints (ingest/browse/search/
# documents, eval batch runs) so the feature is unusable through the product, without taking down the
# shared endpoints above. The agent's runtime knowledge retrieval is likewise unaffected.
if feature_active("knowledge"):
    api_router.include_router(knowledge_router)
if feature_active("eval"):
    api_router.include_router(eval_router)
api_router.include_router(memory_router)
api_router.include_router(config_router)
api_router.include_router(catalog_router)
api_router.include_router(providers_router)
api_router.include_router(preferences_router)
# Feature-gated: when Image Lab is hidden in the feature ledger, its endpoints are
# not mounted at all, so the feature is genuinely unusable (not just hidden in the UI).
if feature_active("image_lab"):
    api_router.include_router(image_lab_router)
api_router.include_router(characters_router)
api_router.include_router(chat_channels_router)
api_router.include_router(channels_router)
api_router.include_router(devices_router)
api_router.include_router(logs_router)
# Feature-gated: metrics_router is exclusive to the Metrics feature (only the Server-page Metrics
# subtab calls /metrics/*), so the whole router is gated — no shared-endpoint split needed.
if feature_active("metrics"):
    api_router.include_router(metrics_router)
api_router.include_router(runtime_router)
api_router.include_router(events_router)


def include_admin_svelte_api(app: Any) -> None:
    """Attach Svelte admin API routes to the admin FastAPI app."""
    app.include_router(api_router)
