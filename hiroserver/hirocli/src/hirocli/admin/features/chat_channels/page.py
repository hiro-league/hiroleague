"""Chat channels — tabbed conversation CRUD + transcript (guidelines §1.2, §1.6)."""

from __future__ import annotations

from hirocli.admin.features.chat_channels.controller import ChatChannelsController
from hirocli.admin.router import admin_router
from hirocli.admin.shared.tab_nav import TabNavRequest
from hirocli.admin.shell.layout import create_page_layout


@admin_router.page("/chats")
async def chat_channels_page(
    tab: str = "channels",
    channel_id: str | None = None,
) -> None:
    create_page_layout(active_path="/chats")
    nav = TabNavRequest(
        tab=tab,
        filters={"channel_id": channel_id},
    )
    await ChatChannelsController(nav).mount()
