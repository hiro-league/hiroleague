"""Gateways — thin page; controller owns UI (guidelines §1.2)."""

from __future__ import annotations

from hirocli.admin.features.gateways.controller import GatewaysPageController
from hirocli.admin.router import admin_router
from hirocli.admin.shell.layout import create_page_layout


@admin_router.page("/gateways")
async def gateways_page() -> None:
    create_page_layout(active_path="/gateways")
    await GatewaysPageController().mount()
