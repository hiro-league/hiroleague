"""Devices — thin page; controller owns UI (guidelines §1.2)."""

from __future__ import annotations

from hirocli.admin.features.devices.controller import DevicePageController
from hirocli.admin.router import admin_router
from hirocli.admin.shell.layout import create_page_layout


@admin_router.page("/devices")
async def devices_page() -> None:
    create_page_layout(active_path="/devices")
    await DevicePageController().mount()
