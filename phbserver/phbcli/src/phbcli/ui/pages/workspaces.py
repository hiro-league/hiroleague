"""Workspaces page — list, create, configure, start, stop, restart, set default, remove.

Safety rules enforced here (in addition to tool-level guards):
  - Stop / Remove: blocked if the target is the workspace hosting this Admin UI.
    The user must start another workspace's Admin UI to perform those actions.
  - Restart: a dialog asks whether to also launch the Admin UI on the restarted
    process. If the current workspace is being restarted the option is forced ON
    and read-only (the UI would disappear otherwise).
"""

from __future__ import annotations

from nicegui import ui


@ui.page("/workspaces")
async def workspaces_page() -> None:
    from phbcli.tools.server import RestartTool, StartTool, StopTool
    from phbcli.tools.workspace import (
        WorkspaceCreateTool,
        WorkspaceListTool,
        WorkspaceRemoveTool,
        WorkspaceUpdateTool,
    )
    from phbcli.ui import state as ui_state
    from phbcli.ui.app import create_page_layout

    create_page_layout(active_path="/workspaces")

    # Id of the workspace whose server process is running this Admin UI.
    current_ws_id: str | None = ui_state.workspace_id

    # Mutable containers so inner async callbacks can reference mutable state.
    pending_remove: list[dict] = [{}]
    pending_edit: list[dict] = [{}]
    pending_restart: list[dict] = [{}]

    # ------------------------------------------------------------------ create dialog
    with ui.dialog() as create_dialog, ui.card().classes("w-96"):
        ui.label("Create workspace").classes("text-lg font-semibold mb-2")
        name_input = ui.input("Name", placeholder="e.g. work").classes("w-full")
        path_input = ui.input(
            "Path (optional)",
            placeholder="Leave blank for default location",
        ).classes("w-full")

        async def do_create() -> None:
            name = name_input.value.strip()
            if not name:
                ui.notify("Name is required.", color="negative")
                return
            path = path_input.value.strip() or None
            try:
                WorkspaceCreateTool().execute(name=name, path=path)
                ui.notify(f"Workspace '{name}' created.", color="positive")
                create_dialog.close()
                name_input.set_value("")
                path_input.set_value("")
                workspace_list.refresh()
            except Exception as exc:
                ui.notify(str(exc), color="negative")

        with ui.row().classes("justify-end gap-2 w-full mt-4"):
            ui.button("Cancel", on_click=create_dialog.close).props("flat")
            ui.button("Create", on_click=do_create)

    # ------------------------------------------------------------------ remove dialog
    with ui.dialog() as remove_dialog, ui.card().classes("w-96"):
        remove_title = ui.label("").classes("text-lg font-semibold mb-2")
        purge_checkbox = ui.checkbox("Also delete workspace folder from disk")

        async def do_remove() -> None:
            row = pending_remove[0]
            ws_id = row.get("id", "")
            ws_name = row.get("name", "")
            try:
                WorkspaceRemoveTool().execute(workspace=ws_id, purge=purge_checkbox.value)
                ui.notify(f"Workspace '{ws_name}' removed.", color="positive")
                remove_dialog.close()
                workspace_list.refresh()
            except Exception as exc:
                ui.notify(str(exc), color="negative")

        with ui.row().classes("justify-end gap-2 w-full mt-4"):
            ui.button("Cancel", on_click=remove_dialog.close).props("flat")
            ui.button("Remove", on_click=do_remove).props('color="negative"')

    # ------------------------------------------------------------------ edit dialog (name, gateway, default)
    with ui.dialog() as edit_dialog, ui.card().classes("w-[480px]"):
        edit_title = ui.label("").classes("text-lg font-semibold mb-2")
        edit_name_input = ui.input("Display name").classes("w-full")
        edit_gateway_input = ui.input(
            "Gateway WebSocket URL",
            placeholder="ws://myhost:8765",
        ).classes("w-full mt-2")
        edit_default_checkbox = ui.checkbox("Set as default workspace").classes("mt-2")
        edit_info = ui.label("").classes("text-xs opacity-60 mt-2")

        async def do_edit() -> None:
            row = pending_edit[0]
            ws_id = row.get("id", "")
            ws_name = row.get("name", "")

            new_name = edit_name_input.value.strip() or None
            new_gateway = edit_gateway_input.value.strip() or None
            make_default = edit_default_checkbox.value

            if new_name is None and new_gateway is None and not make_default:
                ui.notify("Nothing to update.", color="warning")
                return
            try:
                result = WorkspaceUpdateTool().execute(
                    workspace=ws_id,
                    name=new_name,
                    set_default=make_default,
                    gateway_url=new_gateway,
                )
                msgs = []
                if result.renamed:
                    msgs.append(f"renamed to '{result.name}'")
                if result.default_changed:
                    msgs.append("set as default")
                if result.gateway_updated:
                    msgs.append("gateway updated")
                ui.notify(
                    f"Workspace '{ws_name}' updated: {', '.join(msgs) or 'no changes'}.",
                    color="positive",
                )
                edit_dialog.close()
                workspace_list.refresh()
            except Exception as exc:
                ui.notify(str(exc), color="negative")

        with ui.row().classes("justify-end gap-2 w-full mt-4"):
            ui.button("Cancel", on_click=edit_dialog.close).props("flat")
            ui.button("Save", on_click=do_edit)

    # ------------------------------------------------------------------ restart dialog
    with ui.dialog() as restart_dialog, ui.card().classes("w-[440px]"):
        restart_title = ui.label("").classes("text-lg font-semibold mb-2")
        restart_info = ui.label("").classes("text-sm opacity-60 mb-3")
        admin_ui_checkbox = ui.checkbox("Also start Admin UI on the restarted process")

        async def do_restart() -> None:
            row = pending_restart[0]
            ws_id = row.get("id", "")
            ws_name = row.get("name", "")
            try:
                RestartTool().execute(workspace=ws_id, admin=admin_ui_checkbox.value)
                if ws_id == current_ws_id:
                    ui.notify(
                        "Restarting… the Admin UI will be back shortly.",
                        color="info",
                        timeout=6000,
                    )
                else:
                    ui.notify(f"'{ws_name}' restarted.", color="positive")
            except Exception as exc:
                ui.notify(str(exc), color="negative")
            restart_dialog.close()
            workspace_list.refresh()

        with ui.row().classes("justify-end gap-2 w-full mt-4"):
            ui.button("Cancel", on_click=restart_dialog.close).props("flat")
            ui.button("Restart", on_click=do_restart).props('color="warning"')

    # ------------------------------------------------------------------ refreshable table
    @ui.refreshable
    def workspace_list() -> None:
        from pathlib import Path

        from phb_commons.process import is_running, read_pid

        rows: list[dict] = []
        error: str | None = None

        try:
            ws_result = WorkspaceListTool().execute()
            for ws in ws_result.workspaces:
                ws_path = Path(ws["path"])
                pid = read_pid(ws_path, "phbcli.pid")
                running = is_running(pid)
                rows.append({
                    **ws,
                    "running": running,
                    "pid": pid,
                    "is_current": ws["id"] == current_ws_id,
                })
        except Exception as exc:
            error = str(exc)

        if error:
            ui.label(f"Error loading workspaces: {error}").classes("text-negative")
            return

        if not rows:
            with ui.card().classes("w-full"):
                ui.label("No workspaces configured yet. Create one to get started.").classes(
                    "opacity-60 text-sm p-2"
                )
            return

        columns = [
            {"name": "name", "label": "Name", "field": "name", "align": "left", "sortable": True},
            {"name": "setup", "label": "Setup", "field": "is_configured", "align": "left"},
            {"name": "status", "label": "Server", "field": "running", "align": "left"},
            {"name": "gateway_url", "label": "Gateway URL", "field": "gateway_url", "align": "left"},
            {"name": "http_port", "label": "HTTP", "field": "http_port", "align": "left"},
            {"name": "admin_port", "label": "Admin", "field": "admin_port", "align": "left"},
            {"name": "is_default", "label": "Default", "field": "is_default", "align": "center"},
            {"name": "actions", "label": "", "field": "name", "align": "right"},
        ]

        table = ui.table(columns=columns, rows=rows, row_key="id").classes("w-full")

        table.add_slot(
            "body-cell-setup",
            """
            <q-td :props="props">
                <q-badge
                    :color="props.row.is_configured ? 'positive' : 'warning'"
                    :label="props.row.is_configured ? 'Configured' : 'Needs setup'" />
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-status",
            """
            <q-td :props="props">
                <q-badge
                    :color="props.row.running ? 'positive' : 'grey-6'"
                    :label="props.row.running ? 'Running' : 'Stopped'" />
                <q-badge v-if="props.row.is_current" color="info" label="this UI"
                         class="q-ml-xs" />
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-gateway_url",
            """
            <q-td :props="props">
                <span v-if="props.row.gateway_url" class="text-xs font-mono opacity-80">
                    {{ props.row.gateway_url }}
                </span>
                <span v-else class="opacity-30 text-xs">—</span>
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-is_default",
            """
            <q-td :props="props" class="text-center">
                <q-icon v-if="props.row.is_default" name="star" color="warning" size="sm" />
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-actions",
            """
            <q-td :props="props">
              <div class="row no-wrap justify-end items-center">

                <!-- Start: only for configured + stopped workspaces -->
                <q-btn v-if="props.row.is_configured && !props.row.running"
                       flat size="sm" icon="play_arrow" color="positive"
                       title="Start" class="q-ma-xs"
                       @click="() => $parent.$emit('start', props.row)" />

                <!-- Stop: hidden for current workspace; shown for all others -->
                <q-btn v-if="props.row.running && !props.row.is_current"
                       flat size="sm" icon="stop" color="negative"
                       title="Stop" class="q-ma-xs"
                       @click="() => $parent.$emit('stop', props.row)" />

                <!-- Restart: only when running -->
                <q-btn v-if="props.row.running"
                       flat size="sm" icon="restart_alt" color="primary"
                       title="Restart" class="q-ma-xs"
                       @click="() => $parent.$emit('restart', props.row)" />

                <!-- Edit (name, gateway, default) -->
                <q-btn flat size="sm" icon="edit" color="secondary"
                       title="Edit workspace" class="q-ma-xs"
                       @click="() => $parent.$emit('edit', props.row)" />

                <!-- Remove: replaced with lock icon for current workspace -->
                <q-btn v-if="!props.row.is_current"
                       flat size="sm" icon="delete" color="negative"
                       title="Remove" class="q-ma-xs"
                       @click="() => $parent.$emit('remove', props.row)" />
                <q-btn v-if="props.row.is_current"
                       flat size="sm" icon="lock" color="grey-5"
                       title="Cannot remove: this workspace is running the Admin UI"
                       class="q-ma-xs" disable />

              </div>
            </q-td>
            """,
        )

        # ---------------------------------------------------------------- event handlers

        async def handle_start(e) -> None:
            row = e.args if isinstance(e.args, dict) else {}
            ws_id = row.get("id", "")
            ws_name = row.get("name", "")
            try:
                result = StartTool().execute(workspace=ws_id)
                if result.already_running:
                    ui.notify(f"'{ws_name}' is already running.", color="warning")
                else:
                    ui.notify(f"'{ws_name}' started (PID {result.pid}).", color="positive")
            except Exception as exc:
                ui.notify(str(exc), color="negative")
            workspace_list.refresh()

        async def handle_stop(e) -> None:
            row = e.args if isinstance(e.args, dict) else {}
            ws_id = row.get("id", "")
            ws_name = row.get("name", "")
            if ws_id == current_ws_id:
                ui.notify(
                    "Cannot stop the workspace running this Admin UI. "
                    "Start another workspace's Admin UI to do this.",
                    color="negative",
                    timeout=6000,
                )
                return
            try:
                StopTool().execute(workspace=ws_id)
                ui.notify(f"'{ws_name}' stopped.", color="positive")
            except Exception as exc:
                ui.notify(str(exc), color="negative")
            workspace_list.refresh()

        def handle_restart(e) -> None:
            row = e.args if isinstance(e.args, dict) else {}
            pending_restart[0] = row
            ws_id = row.get("id", "")
            ws_name = row.get("name", "")
            is_current = (ws_id == current_ws_id)

            restart_title.set_text(f"Restart workspace '{ws_name}'")
            if is_current:
                restart_info.set_text(
                    "This workspace is running the current Admin UI. "
                    "The Admin UI will restart automatically — keep the option below enabled."
                )
                admin_ui_checkbox.set_value(True)
                admin_ui_checkbox.props(add="disable")
            else:
                restart_info.set_text(f"Path: {row.get('path', '')}")
                admin_ui_checkbox.set_value(False)
                admin_ui_checkbox.props(remove="disable")

            restart_dialog.open()

        def handle_edit(e) -> None:
            row = e.args if isinstance(e.args, dict) else {}
            pending_edit[0] = row
            ws_name = row.get("name", "")
            edit_title.set_text(f"Edit workspace '{ws_name}'")
            edit_name_input.set_value(ws_name)
            edit_gateway_input.set_value(row.get("gateway_url") or "")
            edit_default_checkbox.set_value(row.get("is_default", False))
            http = row.get("http_port", "")
            admin = row.get("admin_port", "")
            edit_info.set_text(
                f"HTTP port: {http}  •  Admin port: {admin}  •  Path: {row.get('path', '')}"
            )
            edit_dialog.open()

        def handle_remove(e) -> None:
            row = e.args if isinstance(e.args, dict) else {}
            ws_id = row.get("id", "")
            ws_name = row.get("name", "")
            if ws_id == current_ws_id:
                ui.notify(
                    "Cannot remove the workspace running this Admin UI. "
                    "Start another workspace's Admin UI to do this.",
                    color="negative",
                    timeout=6000,
                )
                return
            pending_remove[0] = row
            remove_title.set_text(f"Remove workspace '{ws_name}'?")
            purge_checkbox.set_value(False)
            remove_dialog.open()

        table.on("start", handle_start)
        table.on("stop", handle_stop)
        table.on("restart", handle_restart)
        table.on("edit", handle_edit)
        table.on("remove", handle_remove)

    # ------------------------------------------------------------------ page layout
    with ui.column().classes("w-full gap-6 p-6"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("Workspaces").classes("text-2xl font-semibold")
            ui.button("Create workspace", icon="add", on_click=create_dialog.open)

        workspace_list()
