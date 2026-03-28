"""Providers page — workspace credentials (guidelines §2.3)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from nicegui import run, ui

from hirocli.admin.context import get_selected_workspace
from hirocli.admin.features.providers.components import (
    configured_providers_table,
    rows_from_summaries,
)
from hirocli.admin.features.providers.service import ProvidersPageService
from hirocli.admin.shared.ui.confirm_dialog import ConfirmDialogHandles, confirm_dialog
from hirocli.admin.shared.ui.empty_state import empty_state
from hirocli.admin.shared.ui.error_banner import error_banner
from hirocli.admin.shared.ui.loading_state import loading_state


class ProvidersPageController:
    """List configured providers; add key, remove, scan env for selected workspace."""

    def __init__(self) -> None:
        self._service = ProvidersPageService()
        self._refresh_table: Callable[[], None] | None = None
        self._remove_confirm: ConfirmDialogHandles | None = None
        self._pending_remove: dict[str, Any] = {}
        self._add_dialog: ui.dialog | None = None
        self._add_provider_select: ui.select | None = None
        self._add_key_input: ui.input | None = None

    def _refresh(self) -> None:
        if self._refresh_table:
            self._refresh_table()

    async def mount(self) -> None:
        self._remove_confirm = confirm_dialog(
            title="Remove provider",
            message="",
            confirm_label="Remove",
            confirm_icon="delete",
            on_confirm=self._confirm_remove,
        )

        add_dialog = ui.dialog()
        self._add_dialog = add_dialog
        with add_dialog, ui.card().classes("w-full max-w-md"):
            ui.label("Add API key").classes("text-lg font-semibold mb-2")
            self._add_provider_select = ui.select(
                {},
                label="Provider",
            ).classes("w-full").props("dense outlined")
            self._add_key_input = ui.input(label="API key").classes("w-full").props(
                "type=password dense outlined"
            )
            with ui.row().classes("justify-end gap-2 w-full mt-4"):
                ui.button("Cancel", on_click=add_dialog.close).props("flat")
                ui.button(
                    "Save",
                    icon="save",
                    on_click=lambda: asyncio.create_task(self._submit_add()),
                ).props("color=primary")

        @ui.refreshable
        async def provider_table_body() -> None:
            ws = get_selected_workspace()
            if not ws:
                empty_state(
                    message="No workspace selected. Choose one in the sidebar.",
                    icon="storage",
                )
                return

            with ui.column().classes("w-full") as holder:
                with holder:
                    loading_state(message="Loading providers…")
                result = await run.io_bound(self._service.list_configured, ws)
                holder.clear()
                with holder:
                    if not result.ok:
                        error_banner(
                            message=result.error or "Failed to load providers",
                            on_retry=self._refresh,
                        )
                        return
                    rows_raw = result.data or []
                    if not rows_raw:
                        empty_state(
                            message="No providers configured for this workspace. Add an API key or scan your environment.",
                            icon="vpn_key",
                        )
                    else:
                        table = configured_providers_table(rows_from_summaries(rows_raw))
                        table.on("remove", self._on_remove_requested)

        self._refresh_table = provider_table_body.refresh

        with ui.column().classes("w-full gap-6 p-6"):
            ui.label("Providers").classes("text-2xl font-semibold")
            ui.label(
                "Workspace-scoped credentials (OS keyring + providers.json). "
                "Only configured providers contribute models the workspace can use."
            ).classes("text-sm opacity-70 max-w-3xl")

            with ui.row().classes("w-full flex-wrap gap-2 items-center"):
                ui.button(
                    "Add API key",
                    icon="add",
                    on_click=lambda: asyncio.create_task(self._open_add_dialog()),
                ).props("color=primary")
                ui.button(
                    "Scan environment",
                    icon="travel_explore",
                    on_click=lambda: asyncio.create_task(self._scan_env()),
                ).props("outline")
                ui.button("Refresh", icon="refresh", on_click=self._refresh).props("flat")

            await provider_table_body()

    def _on_remove_requested(self, e: Any) -> None:
        row = e.args if isinstance(e.args, dict) else {}
        self._pending_remove = row
        pid = str(row.get("provider_id", ""))
        label = str(row.get("display_label", pid))
        assert self._remove_confirm is not None
        self._remove_confirm.title_label.set_text("Remove provider credentials")
        self._remove_confirm.message_label.set_text(
            f"Remove stored credentials for {label}? This workspace will lose access to that provider's models until you add a key again."
        )
        self._remove_confirm.dialog.open()

    async def _confirm_remove(self) -> bool | None:
        ws = get_selected_workspace()
        pid = str(self._pending_remove.get("provider_id", ""))
        if not ws or not pid:
            ui.notify("Nothing to remove.", color="warning")
            return False
        res = await run.io_bound(self._service.remove_provider, ws, pid)
        if not res.ok:
            ui.notify(res.error or "Remove failed", color="negative")
            return False
        if res.data is False:
            ui.notify("Provider was not configured.", color="warning")
        else:
            ui.notify(f"Removed credentials for {pid}.", color="positive")
        self._refresh()
        return None

    async def _open_add_dialog(self) -> None:
        ws = get_selected_workspace()
        if not ws:
            ui.notify("Select a workspace first.", color="warning")
            return
        res = await run.io_bound(self._service.list_addable_cloud_providers, ws)
        if not res.ok:
            ui.notify(res.error or "Failed to list providers", color="negative")
            return
        addable = res.data or []
        if not addable:
            ui.notify("All cloud catalog providers are already configured.", color="info")
            return
        opts = {p["id"]: f"{p['display_name']} ({p['id']})" for p in addable}
        assert self._add_provider_select is not None
        assert self._add_key_input is not None
        self._add_provider_select.set_options(opts, value=addable[0]["id"])
        self._add_key_input.value = ""
        assert self._add_dialog is not None
        self._add_dialog.open()

    async def _submit_add(self) -> None:
        ws = get_selected_workspace()
        assert self._add_provider_select is not None
        assert self._add_key_input is not None
        pid = str(self._add_provider_select.value or "").strip()
        key = str(self._add_key_input.value or "").strip()
        if not ws:
            ui.notify("Select a workspace first.", color="warning")
            return
        res = await run.io_bound(self._service.add_api_key, ws, pid, key)
        if not res.ok:
            ui.notify(res.error or "Failed to store API key", color="negative")
            return
        ui.notify(f"Stored API key for {pid}.", color="positive")
        assert self._add_dialog is not None
        self._add_dialog.close()
        self._refresh()

    async def _scan_env(self) -> None:
        ws = get_selected_workspace()
        if not ws:
            ui.notify("Select a workspace first.", color="warning")
            return
        res = await run.io_bound(self._service.scan_environment_for_keys, ws)
        if not res.ok:
            ui.notify(res.error or "Scan failed", color="negative")
            return
        n = int(res.data or 0)
        if n == 0:
            ui.notify(
                "No new keys imported (already configured or env vars missing).",
                color="info",
            )
        else:
            ui.notify(f"Imported {n} provider key(s) from the environment.", color="positive")
        self._refresh()
