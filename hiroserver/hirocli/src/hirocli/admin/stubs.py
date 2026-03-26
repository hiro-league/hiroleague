"""Stub routes until each feature is implemented."""

from __future__ import annotations

from nicegui import APIRouter, ui

from hirocli.admin.shell.layout import create_page_layout

_STUBS: list[tuple[str, str, str, str]] = [
    # (route_relative_to_v2_router, nav_path_for_active_state, label, icon)
    # /workspaces implemented in features/workspaces/page.py
    ("/channels", "/v2/channels", "Channels", "cable"),
    ("/gateways", "/v2/gateways", "Gateways", "router"),
    ("/agents", "/v2/agents", "Agents", "smart_toy"),
    ("/devices", "/v2/devices", "Devices", "devices"),
    ("/chats", "/v2/chats", "Chats", "chat"),
    ("/metrics", "/v2/metrics", "Metrics", "monitoring"),
    ("/logs", "/v2/logs", "Logs", "article"),
]


def _make_stub_page(
    router: APIRouter,
    rel_path: str,
    active_path: str,
    label: str,
    icon: str,
) -> None:
    """Register one stub route (factory avoids loop closure bugs)."""

    @router.page(rel_path)
    def _stub_page() -> None:
        create_page_layout(active_path=active_path)
        with ui.column().classes("w-full gap-4 p-6"):
            ui.label(label).classes("text-2xl font-semibold")
            with ui.card().classes("w-full max-w-sm items-center text-center"):
                ui.icon(icon).classes("text-4xl opacity-30 mt-2")
                ui.label("Coming soon").classes("text-lg font-medium opacity-50 mb-1")
                ui.label("This page will be implemented in a later phase.").classes(
                    "text-sm opacity-40 mb-2"
                )


def register_stub_pages(router: APIRouter) -> None:
    """Register Coming soon pages for routes not yet built in v2."""
    for rel_path, nav_path, label, icon in _STUBS:
        _make_stub_page(router, rel_path, nav_path, label, icon)
