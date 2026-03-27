"""Gateways page — setup / start / stop / teardown (guidelines §2.3)."""

from __future__ import annotations

import sys
from collections.abc import Callable
from functools import partial

from nicegui import run, ui

from hirocli.admin.features.gateways.components import gateway_data_table
from hirocli.admin.features.gateways.service import GatewayService
from hirocli.admin.shared.ui.confirm_dialog import confirm_dialog
from hirocli.admin.shared.ui.empty_state import empty_state
from hirocli.admin.shared.ui.error_banner import error_banner
from hirocli.admin.shared.ui.loading_state import loading_state


class GatewaysPageController:
    """Gateway instances are global; selection in the shell does not affect this list."""

    def __init__(self) -> None:
        self._service = GatewayService()
        self._refresh_table: Callable[[], None] | None = None
        self._pending_stop_name = ""
        self._pending_remove_name = ""

    def _refresh(self) -> None:
        if self._refresh_table:
            self._refresh_table()

    def _reset_setup_form(self) -> None:
        self._setup_name_input.set_value("")
        self._setup_key_input.set_value("")
        self._setup_port_input.set_value(None)
        self._setup_host_input.set_value("")
        self._setup_make_default.set_value(False)
        self._setup_skip_autostart.set_value(False)
        self._setup_elevated_task.set_value(False)

    def _build_setup_dialog(self) -> None:
        self._setup_dialog = ui.dialog()
        with self._setup_dialog, ui.card().classes("w-[520px]"):
            ui.label("Create gateway instance").classes("text-lg font-semibold mb-2")

            self._setup_name_input = ui.input("Name *", placeholder="e.g. main").classes("w-full")
            self._setup_key_input = ui.textarea(
                "Desktop public key * (Ed25519, base64)",
                placeholder="Paste the desktop Ed25519 public key here",
            ).classes("w-full mt-2").props("rows=3")
            self._setup_port_input = ui.number(
                "Port *",
                placeholder="e.g. 8765",
                min=1024,
                max=65535,
                precision=0,
            ).classes("w-full mt-2")

            with ui.expansion("Advanced options", icon="tune").classes("w-full mt-2"):
                self._setup_host_input = ui.input(
                    "Host",
                    placeholder="0.0.0.0",
                ).classes("w-full")
                ui.label("Leave blank to bind on all interfaces (0.0.0.0).").classes(
                    "text-xs opacity-50 ml-1 mb-2"
                )

                self._setup_make_default = ui.checkbox("Set as default gateway instance").classes("mt-1")

                self._setup_skip_autostart = ui.checkbox("Skip auto-start registration").classes("mt-1")
                ui.label(
                    "By default, the gateway is registered to start automatically on login."
                ).classes("text-xs opacity-50 ml-6 mb-2")

                if sys.platform == "win32":
                    self._setup_elevated_task = ui.checkbox(
                        "Request elevated Task Scheduler entry (Windows UAC)",
                    ).classes("mt-1")
                    ui.label(
                        "Triggers a UAC prompt on the server machine to register the task "
                        "with highest privileges. Only works if you have physical or RDP "
                        "access to the server."
                    ).classes("text-xs opacity-50 ml-6 mb-1")
                else:
                    self._setup_elevated_task = ui.checkbox("").classes("hidden")

            with ui.row().classes("justify-end gap-2 w-full mt-4"):
                ui.button("Cancel", on_click=self._setup_dialog.close).props("flat")
                ui.button("Create", icon="add", on_click=self._do_setup)

    def _build_stop_confirm(self) -> None:
        self._stop_confirm = confirm_dialog(
            title="Stop gateway?",
            message="This will stop the running gateway process.",
            confirm_label="Stop",
            confirm_icon="stop",
            on_confirm=self._do_stop_confirmed,
        )

    def _build_remove_dialog(self) -> None:
        self._remove_dialog = ui.dialog()
        with self._remove_dialog, ui.card().classes("w-[440px]"):
            self._remove_title = ui.label("").classes("text-lg font-semibold mb-2")
            self._remove_info = ui.label("").classes("text-sm opacity-60 mb-3")
            self._purge_checkbox = ui.checkbox("Also delete instance files from disk")
            ui.label(
                "When enabled, the instance folder and all its files will be permanently deleted."
            ).classes("text-xs opacity-50 ml-6 mb-1")

            with ui.row().classes("justify-end gap-2 w-full mt-4"):
                ui.button("Cancel", on_click=self._remove_dialog.close).props("flat")
                ui.button("Remove", icon="delete", on_click=self._do_remove_confirmed).props(
                    'color="negative"'
                )

    async def _do_setup(self) -> None:
        name = self._setup_name_input.value.strip()
        key = self._setup_key_input.value.strip()
        port_val = self._setup_port_input.value

        if not name:
            ui.notify("Name is required.", color="negative")
            return
        if not key:
            ui.notify("Desktop public key is required.", color="negative")
            return
        if port_val is None:
            ui.notify("Port is required.", color="negative")
            return

        host = self._setup_host_input.value.strip() or "0.0.0.0"
        port_int = int(port_val)

        bound = partial(
            self._service.setup_instance,
            name=name,
            desktop_public_key=key,
            port=port_int,
            host=host,
            log_dir="",
            make_default=bool(self._setup_make_default.value),
            skip_autostart=bool(self._setup_skip_autostart.value),
            elevated_task=bool(self._setup_elevated_task.value),
        )
        res = await run.io_bound(bound)
        if not res.ok:
            ui.notify(res.error or "Setup failed", color="negative")
            return
        ui.notify(res.data or "Gateway created.", color="positive", timeout=8000)
        self._setup_dialog.close()
        self._reset_setup_form()
        self._refresh()

    async def _do_stop_confirmed(self) -> None:
        res = await run.io_bound(self._service.stop, self._pending_stop_name)
        if not res.ok:
            ui.notify(res.error or "Stop failed", color="negative")
            return False
        was_running = res.data is True
        if was_running:
            ui.notify(f"Gateway '{self._pending_stop_name}' stopped.", color="positive")
        else:
            ui.notify(f"Gateway '{self._pending_stop_name}' was not running.", color="warning")
        self._refresh()
        return None

    async def _do_remove_confirmed(self) -> None:
        purge = bool(self._purge_checkbox.value)
        bound = partial(
            self._service.teardown_instance,
            self._pending_remove_name,
            purge=purge,
            elevated_task=False,
        )
        res = await run.io_bound(bound)
        if not res.ok:
            ui.notify(res.error or "Remove failed", color="negative")
            return
        ui.notify(res.data or "Removed.", color="positive", timeout=6000)
        self._remove_dialog.close()
        self._refresh()

    async def _on_start(self, e) -> None:
        row = e.args if isinstance(e.args, dict) else {}
        name = str(row.get("name", ""))
        res = await run.io_bound(self._service.start, name)
        if not res.ok:
            ui.notify(res.error or "Start failed", color="negative")
            self._refresh()
            return
        assert res.data is not None
        already_running, pid = res.data
        if already_running:
            ui.notify(f"Gateway '{name}' is already running.", color="warning")
        else:
            ui.notify(
                f"Gateway '{name}' started (PID {pid}).",
                color="positive",
            )
        self._refresh()

    def _on_stop(self, e) -> None:
        row = e.args if isinstance(e.args, dict) else {}
        name = str(row.get("name", ""))
        self._pending_stop_name = name
        self._stop_confirm.title_label.set_text(f"Stop gateway '{name}'?")
        self._stop_confirm.dialog.open()

    def _on_remove(self, e) -> None:
        row = e.args if isinstance(e.args, dict) else {}
        name = str(row.get("name", ""))
        path = str(row.get("path", ""))
        self._pending_remove_name = name
        self._remove_title.set_text(f"Remove gateway '{name}'?")
        self._remove_info.set_text(f"Path: {path}")
        self._purge_checkbox.set_value(False)
        self._remove_dialog.open()

    async def mount(self) -> None:
        self._build_setup_dialog()
        self._build_stop_confirm()
        self._build_remove_dialog()

        @ui.refreshable
        async def gateway_list() -> None:
            with ui.column().classes("w-full") as holder:
                with holder:
                    loading_state(message="Loading gateways…")
                result = await run.io_bound(self._service.list_instances)
                holder.clear()
                with holder:
                    if not result.ok:
                        error_banner(
                            message=result.error or "Failed to load gateways",
                            on_retry=self._refresh,
                        )
                        return
                    rows = result.data or []
                    if not rows:
                        empty_state(
                            message="No gateway instances configured yet. Create one to get started.",
                            icon="router",
                        )
                        return
                    table = gateway_data_table(rows)
                    table.on("start", self._on_start)
                    table.on("stop", self._on_stop)
                    table.on("remove", self._on_remove)

        self._refresh_table = gateway_list.refresh

        with ui.column().classes("w-full gap-6 p-6"):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("Gateways").classes("text-2xl font-semibold")
                ui.button("Create gateway", icon="add", on_click=self._setup_dialog.open)
            await gateway_list()
