"""LLM catalog browser — thin page (guidelines §1.2)."""

from __future__ import annotations

from hirocli.admin.features.catalog.controller import CatalogPageController
from hirocli.admin.router import admin_router
from hirocli.admin.shell.layout import create_page_layout


@admin_router.page("/catalog")
async def catalog_page() -> None:
    create_page_layout(active_path="/catalog")
    await CatalogPageController().mount()
