"""Logs — thin page; controller owns UI (guidelines §1.2)."""

from __future__ import annotations

from hirocli.admin.features.logs.controller import LogsPageController
from hirocli.admin.router import admin_router
from hirocli.admin.shell.layout import create_page_layout


@admin_router.page("/logs")
async def logs_page() -> None:
    create_page_layout(active_path="/logs")
    await LogsPageController().mount()
