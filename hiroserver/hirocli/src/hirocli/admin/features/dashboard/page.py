"""Dashboard — thin page: service Result, loading/error/empty/data (guidelines §1.2, §2.4)."""

from __future__ import annotations

from nicegui import run, ui

from hirocli.admin.features.dashboard.components import (
    maybe_render_no_workspaces_hint,
    render_dashboard_overview,
)
from hirocli.admin.features.dashboard.service import DashboardService
from hirocli.admin.router import V2_ROOT, v2_router
from hirocli.admin.shared.ui.error_banner import error_banner
from hirocli.admin.shared.ui.loading_state import loading_state
from hirocli.admin.shell.layout import create_page_layout


def _load_dashboard_overview():
    """Thread-pool entry: bound method / closure not required for io_bound."""
    return DashboardService().get_overview()


@v2_router.page("/")
async def dashboard_page() -> None:
    create_page_layout(active_path=V2_ROOT)

    with ui.column().classes("w-full gap-6 p-6"):
        ui.label("Dashboard").classes("text-2xl font-semibold")
        with ui.column().classes("w-full") as body:
            with body:
                loading_state(message="Loading dashboard…")
            result = await run.io_bound(_load_dashboard_overview)
            body.clear()
            with body:
                if not result.ok:
                    error_banner(
                        message=result.error or "Failed to load dashboard",
                        on_retry=lambda: ui.navigate.reload(),
                    )
                else:
                    data = result.data
                    assert data is not None
                    maybe_render_no_workspaces_hint(data)
                    render_dashboard_overview(data)
