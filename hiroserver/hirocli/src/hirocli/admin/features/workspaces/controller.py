"""Workspaces page controller — dialogs, table, and service calls (guidelines §2.3)."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from nicegui import run, ui

from hirocli.admin.features.workspaces.components import workspace_data_table
from hirocli.admin.features.workspaces.service import WorkspaceService
from hirocli.admin.shared.result import Result
from hirocli.admin.shared.ui.loading_state import loading_state
from hirocli.admin.shared.ui.warning_callout import warning_callout


class WorkspacesPageController:
    """Owns v2 workspaces UI state and wires the table to WorkspaceService."""

    def __init__(self, hosting_workspace_id: str | None) -> None:
        self._hosting = hosting_workspace_id
        self._service = WorkspaceService()
        self._refresh_table: Callable[[], None] | None = None
        self._pending_remove: dict[str, Any] = {}
        self._pending_edit: dict[str, Any] = {}
        self._pending_restart: dict[str, Any] = {}
        self._pending_setup: dict[str, Any] = {}
        self._pending_pubkey: dict[str, Any] = {}

    def _refresh(self) -> None:
        if self._refresh_table:
            self._refresh_table()

    async def _copy_pubkey_to_clipboard(self) -> None:
        ui.clipboard.write(self._pubkey_display.value)
        ui.notify("Public key copied to clipboard.", color="positive", timeout=2500)

    async def _copy_setup_pubkey_to_clipboard(self) -> None:
        ui.clipboard.write(self._setup_pubkey_display.value)
        ui.notify("Public key copied to clipboard.", color="positive", timeout=2500)

    async def mount(self) -> None:
        self._build_create_dialog()
        self._build_remove_dialog()
        self._build_edit_dialog()
        self._build_restart_dialog()
        self._build_pubkey_dialog()
        self._build_setup_dialog()

        # Async refreshable: loading state while list_rows runs off the UI thread (guidelines §2.4).
        @ui.refreshable
        async def workspace_table() -> None:
            with ui.column().classes("w-full") as holder:
                with holder:
                    loading_state(message="Loading workspaces…")
                result = await run.io_bound(self._service.list_rows, self._hosting)
                holder.clear()
                with holder:
                    self._render_workspace_table_body(result)

        self._refresh_table = workspace_table.refresh

        with ui.column().classes("w-full gap-6 p-6"):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("Workspaces").classes("text-2xl font-semibold")
                ui.button("Create workspace", icon="add", on_click=self._create_dialog.open)
            await workspace_table()

    # ------------------------------------------------------------------ dialogs

    def _build_create_dialog(self) -> None:
        self._create_dialog = ui.dialog()
        with self._create_dialog, ui.card().classes("w-96"):
            ui.label("Create workspace").classes("text-lg font-semibold mb-2")
            self._create_name = ui.input("Name", placeholder="e.g. work").classes("w-full")
            self._create_path = ui.input(
                "Path (optional)",
                placeholder="Leave blank for default location",
            ).classes("w-full")
            with ui.row().classes("justify-end gap-2 w-full mt-4"):
                ui.button("Cancel", on_click=self._create_dialog.close).props("flat")
                ui.button("Create", on_click=self._on_create)

    async def _on_create(self) -> None:
        name = self._create_name.value.strip()
        path = self._create_path.value.strip() or None
        r = self._service.create(name, path)
        if not r.ok:
            ui.notify(r.error or "Create failed", color="negative")
            return
        ui.notify(r.data or "Created.", color="positive")
        self._create_dialog.close()
        self._create_name.set_value("")
        self._create_path.set_value("")
        self._refresh()

    def _build_remove_dialog(self) -> None:
        self._remove_dialog = ui.dialog()
        with self._remove_dialog, ui.card().classes("w-96"):
            self._remove_title = ui.label("").classes("text-lg font-semibold mb-2")
            self._remove_purge = ui.checkbox("Also delete workspace folder from disk")
            with ui.row().classes("justify-end gap-2 w-full mt-4"):
                ui.button("Cancel", on_click=self._remove_dialog.close).props("flat")
                ui.button("Remove", on_click=self._on_remove).props('color="negative"')

    async def _on_remove(self) -> None:
        row = self._pending_remove
        ws_id = str(row.get("id", ""))
        r = self._service.remove(ws_id, self._remove_purge.value, self._hosting)
        if not r.ok:
            ui.notify(r.error or "Remove failed", color="negative")
            return
        ui.notify(r.data or "Removed.", color="positive")
        self._remove_dialog.close()
        self._refresh()

    def _build_edit_dialog(self) -> None:
        self._edit_dialog = ui.dialog()
        with self._edit_dialog, ui.card().classes("w-[480px]"):
            self._edit_title = ui.label("").classes("text-lg font-semibold mb-2")
            self._edit_name = ui.input("Display name").classes("w-full")
            self._edit_gateway = ui.input(
                "Gateway WebSocket URL",
                placeholder="ws://myhost:8765",
            ).classes("w-full mt-2")
            self._edit_default = ui.checkbox("Set as default workspace").classes("mt-2")
            self._edit_info = ui.label("").classes("text-xs opacity-60 mt-2")
            with ui.row().classes("justify-end gap-2 w-full mt-4"):
                ui.button("Cancel", on_click=self._edit_dialog.close).props("flat")
                ui.button("Save", on_click=self._on_edit)

    async def _on_edit(self) -> None:
        row = self._pending_edit
        ws_id = str(row.get("id", ""))
        prev_name = str(row.get("name", ""))
        new_name = self._edit_name.value.strip() or None
        new_gateway = self._edit_gateway.value.strip() or None
        make_default = self._edit_default.value
        r = self._service.update(
            ws_id,
            name=new_name,
            gateway_url=new_gateway,
            set_default=make_default,
            previous_display_name=prev_name,
        )
        if not r.ok:
            ui.notify(r.error or "Update failed", color="negative")
            return
        ui.notify(r.data or "Updated.", color="positive")
        self._edit_dialog.close()
        self._refresh()

    def _build_restart_dialog(self) -> None:
        self._restart_dialog = ui.dialog()
        with self._restart_dialog, ui.card().classes("w-[440px]"):
            self._restart_title = ui.label("").classes("text-lg font-semibold mb-2")
            self._restart_info = ui.label("").classes("text-sm opacity-60 mb-3")
            self._restart_admin_ui = ui.checkbox("Also start Admin UI on the restarted process")
            with ui.row().classes("justify-end gap-2 w-full mt-4"):
                ui.button("Cancel", on_click=self._restart_dialog.close).props("flat")
                ui.button("Restart", on_click=self._on_restart).props('color="warning"')

    async def _on_restart(self) -> None:
        row = self._pending_restart
        ws_id = str(row.get("id", ""))
        ws_name = str(row.get("name", ""))
        r = self._service.restart(ws_id, admin=self._restart_admin_ui.value)
        if not r.ok:
            ui.notify(r.error or "Restart failed", color="negative")
        elif ws_id == self._hosting:
            ui.notify(
                "Restarting… the Admin UI will be back shortly.",
                color="info",
                timeout=6000,
            )
        else:
            ui.notify(f"'{ws_name}' restarted.", color="positive")
        self._restart_dialog.close()
        self._refresh()

    def _build_pubkey_dialog(self) -> None:
        self._pubkey_dialog = ui.dialog()
        with self._pubkey_dialog, ui.card().classes("w-[520px]"):
            self._pubkey_title = ui.label("").classes("text-lg font-semibold mb-1")
            with ui.column().classes("w-full mb-3"):
                warning_callout(
                    message=(
                        "This key must be registered in every gateway instance that trusts this "
                        "workspace. Regenerating it invalidates all existing gateway trust relationships."
                    ),
                )
            ui.label("Workspace public key (Ed25519, base64):").classes(
                "text-xs font-semibold opacity-70"
            )
            with ui.row().classes("w-full items-start gap-2"):
                self._pubkey_display = ui.textarea().classes("w-full font-mono text-xs").props(
                    "readonly rows=3 outlined"
                )
                ui.button(icon="content_copy", on_click=self._copy_pubkey_to_clipboard).props(
                    "flat dense"
                ).classes("mt-1 shrink-0").tooltip("Copy to clipboard")
            with ui.row().classes("justify-between w-full mt-4"):
                ui.button("Regenerate key", icon="autorenew", on_click=self._on_regenerate_key).props(
                    'color="warning" outline'
                )
                ui.button("Close", on_click=self._pubkey_dialog.close).props("flat")

    async def _on_regenerate_key(self) -> None:
        row = self._pending_pubkey
        ws_id = str(row.get("id", ""))
        ws_name = str(row.get("name", ""))
        r = self._service.regenerate_key(ws_id)
        if not r.ok:
            ui.notify(r.error or "Regenerate failed", color="negative")
            return
        self._pubkey_display.set_value(r.data or "")
        ui.notify(
            f"New key generated for '{ws_name}'. Update your gateway instance.",
            color="warning",
            timeout=6000,
        )

    def _build_setup_dialog(self) -> None:
        self._setup_dialog = ui.dialog().props("persistent")
        with self._setup_dialog, ui.card().classes("w-[520px]"):
            self._setup_form_panel = ui.column().classes("w-full gap-0")
            with self._setup_form_panel:
                self._setup_title = ui.label("").classes("text-lg font-semibold mb-1")
                self._setup_path_info = ui.label("").classes("text-xs opacity-50 mb-3")
                self._setup_gateway = ui.input(
                    "Gateway WebSocket URL *",
                    placeholder="ws://myhost:8765",
                ).classes("w-full")
                with ui.expansion("Advanced options", icon="tune").classes("w-full mt-2"):
                    self._setup_port = ui.number(
                        "HTTP port override",
                        placeholder="Leave blank to use auto-assigned port",
                        min=1024,
                        max=65535,
                        precision=0,
                    ).classes("w-full")
                    self._setup_port_info = ui.label("").classes("text-xs opacity-50 mt-1 mb-2")
                    self._setup_skip_autostart = ui.checkbox("Skip auto-start registration").classes("mt-1")
                    ui.label(
                        "By default, the server is registered to start automatically on login."
                    ).classes("text-xs opacity-50 ml-6 mb-2")
                    self._setup_start_server = ui.checkbox(
                        "Start server immediately after setup",
                    ).classes("mt-1")
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

            self._setup_key_panel = ui.column().classes("w-full gap-3")
            with self._setup_key_panel:
                with ui.row().classes("items-center gap-2"):
                    ui.icon("check_circle").classes("text-positive text-2xl")
                    self._setup_key_ws_label = ui.label("").classes("text-lg font-semibold")
                with ui.column().classes("w-full"):
                    warning_callout(
                        message=(
                            "Save this public key — it will not be shown again. "
                            "You must paste it into the Desktop public key field "
                            "when creating a gateway instance for this workspace."
                        ),
                    )
                ui.label("Workspace public key (Ed25519, base64):").classes(
                    "text-xs font-semibold opacity-70 mt-1"
                )
                with ui.row().classes("w-full items-start gap-2"):
                    self._setup_pubkey_display = ui.textarea().classes("w-full font-mono text-xs").props(
                        "readonly rows=3 outlined"
                    )
                    ui.button(
                        icon="content_copy",
                        on_click=self._copy_setup_pubkey_to_clipboard,
                    ).props("flat dense").classes("mt-1 shrink-0").tooltip("Copy to clipboard")
                with ui.row().classes("justify-end w-full mt-2"):
                    ui.button(
                        "I've saved the key — close",
                        icon="lock",
                        on_click=self._dismiss_setup_key_panel,
                    ).props('color="primary"')

            self._setup_key_panel.set_visibility(False)

            with self._setup_form_panel:
                with ui.row().classes("justify-end gap-2 w-full mt-4"):
                    ui.button("Cancel", on_click=self._setup_dialog.close).props("flat")
                    self._setup_run_btn = ui.button("Run setup", icon="settings")
            self._setup_run_btn.on("click", self._on_setup)

    def _reset_setup_form(self) -> None:
        self._setup_gateway.set_value("")
        self._setup_port.set_value(None)
        self._setup_skip_autostart.set_value(False)
        self._setup_start_server.set_value(False)
        self._setup_elevated_task.set_value(False)
        self._setup_pubkey_display.set_value("")

    def _dismiss_setup_key_panel(self) -> None:
        self._setup_key_panel.set_visibility(False)
        self._setup_form_panel.set_visibility(True)
        self._reset_setup_form()
        self._setup_dialog.close()

    async def _on_setup(self) -> None:
        row = self._pending_setup
        ws_id = str(row.get("id", ""))
        gateway = self._setup_gateway.value.strip()
        port_val = self._setup_port.value
        http_port: int | None = int(port_val) if port_val else None
        r = self._service.setup(
            ws_id,
            gateway_url=gateway,
            http_port=http_port,
            skip_autostart=self._setup_skip_autostart.value,
            start_server=self._setup_start_server.value,
            elevated_task=self._setup_elevated_task.value,
        )
        if not r.ok:
            ui.notify(r.error or "Setup failed", color="negative")
            return
        result = r.data
        assert result is not None
        self._setup_key_ws_label.set_text(f"Workspace '{result.workspace}' configured")
        self._setup_pubkey_display.set_value(result.desktop_pub)
        self._setup_form_panel.set_visibility(False)
        self._setup_key_panel.set_visibility(True)
        self._refresh()

    # ------------------------------------------------------------------ table

    def _render_workspace_table_body(self, result: Result[list[dict[str, Any]]]) -> None:
        if not result.ok:
            ui.label(f"Error loading workspaces: {result.error}").classes("text-negative")
            return
        rows = result.data or []
        if not rows:
            with ui.card().classes("w-full"):
                ui.label("No workspaces configured yet. Create one to get started.").classes(
                    "opacity-60 text-sm p-2"
                )
            return

        table = workspace_data_table(rows)

        table.on("setup", self._handle_setup)
        table.on("pubkey", self._handle_pubkey)
        table.on("open-folder", self._handle_open_folder)
        table.on("start", self._handle_start)
        table.on("stop", self._handle_stop)
        table.on("restart", self._handle_restart)
        table.on("edit", self._handle_edit)
        table.on("remove", self._handle_remove)

    def _handle_setup(self, e) -> None:
        row = e.args if isinstance(e.args, dict) else {}
        self._pending_setup = row
        ws_name = str(row.get("name", ""))
        self._setup_title.set_text(f"Setup workspace '{ws_name}'")
        self._setup_path_info.set_text(f"Path: {row.get('path', '')}")
        self._setup_gateway.set_value(row.get("gateway_url") or "")
        self._setup_port.set_value(None)
        self._setup_port_info.set_text(f"Auto-assigned HTTP port: {row.get('http_port', 'unknown')}")
        self._setup_skip_autostart.set_value(False)
        self._setup_start_server.set_value(False)
        self._setup_elevated_task.set_value(False)
        self._setup_key_panel.set_visibility(False)
        self._setup_form_panel.set_visibility(True)
        self._setup_dialog.open()

    def _handle_pubkey(self, e) -> None:
        row = e.args if isinstance(e.args, dict) else {}
        self._pending_pubkey = row
        ws_name = str(row.get("name", ""))
        ws_id = str(row.get("id", ""))
        self._pubkey_title.set_text(f"Public key — '{ws_name}'")
        self._pubkey_display.set_value("")
        r = self._service.get_public_key(ws_id)
        if not r.ok:
            ui.notify(r.error or "Failed to load public key", color="negative")
            return
        self._pubkey_display.set_value(r.data or "")
        self._pubkey_dialog.open()

    def _handle_open_folder(self, e) -> None:
        row = e.args if isinstance(e.args, dict) else {}
        folder_path = str(row.get("path", ""))
        r = self._service.open_folder(folder_path)
        if not r.ok:
            ui.notify(r.error or "Open folder failed", color="negative")
            return
        ui.notify(f"Opening folder: {folder_path}", color="info", timeout=2000)

    async def _handle_start(self, e) -> None:
        row = e.args if isinstance(e.args, dict) else {}
        ws_id = str(row.get("id", ""))
        r = self._service.start(ws_id)
        if not r.ok:
            ui.notify(r.error or "Start failed", color="negative")
            self._refresh()
            return
        data = r.data
        assert data is not None
        name, already, pid = data
        if already:
            ui.notify(f"'{name}' is already running.", color="warning")
        else:
            ui.notify(f"'{name}' started (PID {pid}).", color="positive")
        self._refresh()

    async def _handle_stop(self, e) -> None:
        row = e.args if isinstance(e.args, dict) else {}
        ws_id = str(row.get("id", ""))
        ws_name = str(row.get("name", ""))
        r = self._service.stop(ws_id, self._hosting)
        if not r.ok:
            ui.notify(r.error or "Stop failed", color="negative", timeout=6000)
            self._refresh()
            return
        ui.notify(r.data or f"'{ws_name}' stopped.", color="positive")
        self._refresh()

    def _handle_restart(self, e) -> None:
        row = e.args if isinstance(e.args, dict) else {}
        self._pending_restart = row
        ws_id = str(row.get("id", ""))
        ws_name = str(row.get("name", ""))
        is_current = ws_id == self._hosting
        self._restart_title.set_text(f"Restart workspace '{ws_name}'")
        if is_current:
            self._restart_info.set_text(
                "This workspace is running the current Admin UI. "
                "The Admin UI will restart automatically — keep the option below enabled."
            )
            self._restart_admin_ui.set_value(True)
            self._restart_admin_ui.props(add="disable")
        else:
            self._restart_info.set_text(f"Path: {row.get('path', '')}")
            self._restart_admin_ui.set_value(False)
            self._restart_admin_ui.props(remove="disable")
        self._restart_dialog.open()

    def _handle_edit(self, e) -> None:
        row = e.args if isinstance(e.args, dict) else {}
        self._pending_edit = row
        ws_name = str(row.get("name", ""))
        self._edit_title.set_text(f"Edit workspace '{ws_name}'")
        self._edit_name.set_value(ws_name)
        self._edit_gateway.set_value(row.get("gateway_url") or "")
        self._edit_default.set_value(row.get("is_default", False))
        http = row.get("http_port", "")
        admin = row.get("admin_port", "")
        self._edit_info.set_text(f"HTTP port: {http}  •  Admin port: {admin}  •  Path: {row.get('path', '')}")
        self._edit_dialog.open()

    def _handle_remove(self, e) -> None:
        row = e.args if isinstance(e.args, dict) else {}
        ws_id = str(row.get("id", ""))
        ws_name = str(row.get("name", ""))
        if self._hosting is not None and ws_id == self._hosting:
            ui.notify(
                "Cannot remove the workspace running this Admin UI. "
                "Start another workspace's Admin UI to do this.",
                color="negative",
                timeout=6000,
            )
            return
        self._pending_remove = row
        self._remove_title.set_text(f"Remove workspace '{ws_name}'?")
        self._remove_purge.set_value(False)
        self._remove_dialog.open()
