"""Channels — thin page; controller owns UI (guidelines §1.2)."""

from __future__ import annotations

from hirocli.admin.features.channels.controller import ChannelsPageController
from hirocli.admin.router import admin_router
from hirocli.admin.shell.layout import create_page_layout


@admin_router.page("/channels")
async def channels_page() -> None:
    create_page_layout(active_path="/channels")
    await ChannelsPageController().mount()
