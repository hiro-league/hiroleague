"""Server metrics — thin page; controller owns live charts (guidelines §1.2)."""

from __future__ import annotations

from hirocli.admin.features.metrics.controller import MetricsPageController
from hirocli.admin.router import admin_router
from hirocli.admin.shell.layout import create_page_layout


@admin_router.page("/metrics")
async def metrics_page() -> None:
    create_page_layout(active_path="/metrics")
    await MetricsPageController().mount()
