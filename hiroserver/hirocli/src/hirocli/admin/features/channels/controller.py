"""Channels page — refreshable list and enable/disable (guidelines §2.3)."""

from __future__ import annotations

from collections.abc import Callable

from nicegui import run, ui

from hirocli.admin.context import get_selected_workspace
from hirocli.admin.features.channels.components import channel_data_table
from hirocli.admin.features.channels.service import ChannelService
from hirocli.admin.shared.ui.empty_state import empty_state
from hirocli.admin.shared.ui.error_banner import error_banner
from hirocli.admin.shared.ui.loading_state import loading_state


class ChannelsPageController:
    """Owns channel table refresh and wires actions to ChannelService."""

    def __init__(self) -> None:
        self._service = ChannelService()
        self._refresh_table: Callable[[], None] | None = None

    def _refresh(self) -> None:
        if self._refresh_table:
            self._refresh_table()

    async def _on_enable(self, e) -> None:
        row = e.args if isinstance(e.args, dict) else {}
        name = str(row.get("name", ""))
        ws = get_selected_workspace()
        res = await run.io_bound(self._service.enable_channel, name, ws)
        if res.ok:
            ui.notify(res.data or "Enabled.", color="positive")
        else:
            ui.notify(res.error or "Enable failed", color="negative")
        self._refresh()

    async def _on_disable(self, e) -> None:
        row = e.args if isinstance(e.args, dict) else {}
        name = str(row.get("name", ""))
        ws = get_selected_workspace()
        res = await run.io_bound(self._service.disable_channel, name, ws)
        if res.ok:
            ui.notify(res.data or "Disabled.", color="positive")
        else:
            ui.notify(res.error or "Disable failed", color="negative")
        self._refresh()

    async def mount(self) -> None:
        @ui.refreshable
        async def channel_table() -> None:
            ws_id = get_selected_workspace()
            if not ws_id:
                empty_state(
                    message="No workspace selected. Choose one in the sidebar.",
                    icon="storage",
                )
                return
            with ui.column().classes("w-full") as holder:
                with holder:
                    loading_state(message="Loading channels…")
                result = await run.io_bound(self._service.list_channels, ws_id)
                holder.clear()
                with holder:
                    if not result.ok:
                        error_banner(
                            message=result.error or "Failed to load channels",
                            on_retry=self._refresh,
                        )
                        return
                    rows = result.data or []
                    if not rows:
                        empty_state(
                            message="No channels configured for this workspace.",
                            icon="cable",
                        )
                        return
                    table = channel_data_table(rows)
                    table.on("enable", self._on_enable)
                    table.on("disable", self._on_disable)

        self._refresh_table = channel_table.refresh

        with ui.column().classes("w-full gap-6 p-6"):
            ui.label("Channels").classes("text-2xl font-semibold")
            await channel_table()
