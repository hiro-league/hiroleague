"""Admin metrics tick / configure routes."""

from __future__ import annotations

import dataclasses
from typing import Any

from fastapi import APIRouter

from hirocli.admin.features.metrics.service import MetricsAdminService
from hirocli.admin_svelte.metrics_access import _metrics_collector
from hirocli.admin_svelte.result_payload import _api_data, api_failure
from hirocli.admin_svelte.schemas import MetricsConfigureRequest

metrics_router = APIRouter()


@metrics_router.get("/metrics/tick")
async def metrics_tick() -> Any:
    collector = _metrics_collector()
    if collector is None:
        return {
                "available": False,
                "enabled": False,
                "interval": 2.0,
                "status_text": "Metrics collector is not available.",
                "frame": None,
            }

    payload = MetricsAdminService().prepare_tick(collector)
    frame = dataclasses.asdict(payload.frame) if payload.frame is not None else None
    return {
            "available": True,
            "enabled": collector.enabled,
            "interval": collector.interval,
            "status_text": payload.status_text,
            "frame": frame,
        }


@metrics_router.post("/metrics/configure")
async def configure_metrics_for_admin(body: MetricsConfigureRequest) -> Any:
    collector = _metrics_collector()
    if collector is None:
        return api_failure("Metrics collector is not available.")
    result = MetricsAdminService().configure(
        collector,
        enabled=body.enabled,
        interval=body.interval,
    )
    return _api_data(result)
