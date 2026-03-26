"""Shared chrome: header, drawer (nav + bottom workspace selector), dark mode, reconnect toast."""

from __future__ import annotations

import asyncio
from typing import Any

from nicegui import app as nicegui_app, ui

from hirocli.admin.context import ensure_selected_workspace_storage, get_runtime_context
from hirocli.admin.shell.navigation import NAV
from hirocli.admin.shell.workspace_service import WorkspaceSelectService

# Shell-only: show full select when drawer expanded, icon+menu when mini (Quasar sets q-drawer--mini).
WORKSPACE_DRAWER_MINI_CSS = """
.q-drawer--mini .admin-v2-workspace-select-wrap { display: none !important; }
.q-drawer:not(.q-drawer--mini) .admin-v2-workspace-mini-wrap { display: none !important; }
"""


def register_shell_shared_styles() -> None:
    """Register once from admin v2 bootstrap (NiceGUI shared CSS for all clients)."""
    from nicegui import ui

    ui.add_css(WORKSPACE_DRAWER_MINI_CSS.strip(), shared=True)


def create_page_layout(active_path: str = "/") -> None:
    """Render shell. Call at the start of every @ui.page handler."""
    ctx = get_runtime_context()
    hosting_id = ctx.hosting_workspace_id if ctx else None
    hosting_name = ctx.hosting_workspace_name if ctx else None

    workspace_options, default_ws_id = WorkspaceSelectService.load_select_options(hosting_id)
    ws_ids = list(workspace_options.keys())
    selected_id = ensure_selected_workspace_storage(ws_ids, default_ws_id)

    if "sidebar_mini" not in nicegui_app.storage.user:
        nicegui_app.storage.user["sidebar_mini"] = False
    sidebar_mini = nicegui_app.storage.user["sidebar_mini"]

    drawer = ui.left_drawer(value=True).props(
        'behavior="desktop" bordered :width="210" :mini-width="88"'
    )
    if sidebar_mini:
        drawer.props(add="mini")

    with drawer:
        with ui.column().classes("w-full h-full flex flex-col"):
            with ui.column().classes("w-full flex-1 min-h-0 overflow-y-auto py-0"):
                _sidebar_nav(active_path)
            if workspace_options:
                _sidebar_workspace_footer(
                    workspace_options,
                    selected_id,
                )

    ui.dark_mode().bind_value(nicegui_app.storage.user, "dark_mode")

    header_title = "Hiro Admin (v2)"
    if hosting_name:
        header_title = f"Hiro Admin (v2) — {hosting_name}"

    with ui.header(elevated=True).classes(
        "items-center justify-between q-py-none !p-2 min-h-[40px]"
    ):
        with ui.row().classes("items-center gap-1"):
            ui.button(icon="menu", on_click=lambda: _toggle_sidebar_mini(drawer)).props(
                'flat dense round color="white" size="sm"'
            )
            ui.icon("home").classes("text-primary text-lg")
            ui.label(header_title).classes("text-sm font-semibold")

        with ui.row().classes("items-center gap-2"):
            _theme_toggle_btn: list[Any] = []

            def _toggle_dark_mode() -> None:
                storage = nicegui_app.storage.user
                storage["dark_mode"] = not storage.get("dark_mode", False)
                is_dark = storage["dark_mode"]
                # Icon-only: label + switch track were low-contrast on primary header in dark theme.
                _theme_toggle_btn[0].props(
                    f'icon={"light_mode" if is_dark else "dark_mode"}'
                )
                _theme_toggle_btn[0].tooltip(
                    "Switch to light mode" if is_dark else "Switch to dark mode"
                )

            initial_dark = nicegui_app.storage.user.get("dark_mode", False)
            theme_btn = ui.button(
                icon="light_mode" if initial_dark else "dark_mode",
                on_click=_toggle_dark_mode,
            ).props('flat dense round color="white" size="sm"')
            _theme_toggle_btn.append(theme_btn)
            theme_btn.tooltip(
                "Switch to light mode" if initial_dark else "Switch to dark mode"
            )

    from nicegui import context as _ctx

    _current_client = _ctx.client
    asyncio.create_task(_reconnect_toast(_current_client))


def _toggle_sidebar_mini(drawer: Any) -> None:
    nicegui_app.storage.user["sidebar_mini"] = not nicegui_app.storage.user["sidebar_mini"]
    mini = nicegui_app.storage.user["sidebar_mini"]
    if mini:
        drawer.props(add="mini")
    else:
        drawer.props(remove="mini")


def _on_workspace_change_reload(e) -> None:
    nicegui_app.storage.user["selected_workspace"] = e.value
    ui.navigate.reload()


def _pick_workspace_and_reload(workspace_id: str) -> None:
    nicegui_app.storage.user["selected_workspace"] = workspace_id
    ui.navigate.reload()


def _sidebar_workspace_footer(
    workspace_options: dict[str, str],
    selected_id: str | None,
) -> None:
    """Bottom of drawer: full select (expanded) or icon+menu (mini); CSS swaps visibility."""
    with ui.column().classes("w-full shrink-0 gap-1 pt-1 pb-2"):
        ui.separator()
        ui.label("Workspace").classes(
            "text-xs font-semibold uppercase tracking-wider opacity-50 px-3 q-mini-drawer-hide"
        )
        with ui.column().classes("admin-v2-workspace-select-wrap w-full px-2"):
            ui.select(
                workspace_options,
                value=selected_id,
                on_change=_on_workspace_change_reload,
            ).classes("w-full text-[0.8rem]").props("dense outlined dark hide-bottom-space")

        with ui.row().classes("admin-v2-workspace-mini-wrap w-full justify-center px-0"):
            with ui.button(icon="folder_open").props("flat dense round color=primary") as _ws_btn:
                with ui.menu():
                    for ws_id, label in workspace_options.items():
                        ui.menu_item(
                            label,
                            on_click=lambda wid=ws_id: _pick_workspace_and_reload(wid),
                        )
            _ws_btn.tooltip("Switch workspace")


def _sidebar_nav(active_path: str) -> None:
    """Nav links only (workspace selector lives in footer)."""
    with ui.column().classes("w-full py-0"):
        for item in NAV:
            group, label, icon, path = item
            if group is None:
                ui.label(label).classes(
                    "text-xs font-semibold uppercase tracking-wider opacity-50 px-4 pt-1 pb-0 q-mini-drawer-hide"
                )
            else:
                assert path is not None
                is_active = path == active_path
                with ui.item(on_click=lambda p=path: ui.navigate.to(p)).props(
                    "clickable v-ripple dense"
                ).classes("rounded-md mx-2 my-0" + (" text-primary" if is_active else "")):
                    with ui.item_section().props("avatar").classes("min-w-0 px-2 py-2"):
                        if icon:
                            icon_elem = ui.icon(icon).classes(
                                "text-lg " + ("text-primary" if is_active else "opacity-60")
                            )
                            icon_elem.tooltip(label)
                    with ui.item_section().classes("q-mini-drawer-hide"):
                        ui.label(label).classes("text-sm")


async def _reconnect_toast(client) -> None:
    try:
        is_reconnect = await client.run_javascript(
            """
            const was = sessionStorage.getItem('hiro_admin_v2_connected');
            sessionStorage.setItem('hiro_admin_v2_connected', '1');
            return was !== null;
            """,
            timeout=5,
        )
        if is_reconnect:
            client.outbox.enqueue_message(
                "notify",
                {
                    "message": "Back Online",
                    "color": "positive",
                    "icon": "check_circle",
                    "position": "bottom",
                    "timeout": 3000,
                },
                client.id,
            )
    except Exception:
        pass
