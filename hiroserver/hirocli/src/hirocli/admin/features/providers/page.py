"""Providers — thin page (guidelines §1.2)."""

from __future__ import annotations

from hirocli.admin.features.providers.controller import ProvidersPageController
from hirocli.admin.router import admin_router
from hirocli.admin.shell.layout import create_page_layout


@admin_router.page("/providers")
async def providers_page() -> None:
    create_page_layout(active_path="/providers")
    await ProvidersPageController().mount()
