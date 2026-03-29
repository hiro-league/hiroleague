"""Stub routes until each feature is implemented."""

from __future__ import annotations

from nicegui import APIRouter, ui

from hirocli.admin.shell.layout import create_page_layout

# (route, nav_path, label, icon[, stub_detail])
_STUBS: list[tuple[str, str, str, str] | tuple[str, str, str, str, str]] = [
    # /workspaces implemented in features/workspaces/page.py
    # /channels, /characters, /devices — features/*/page.py
    # /gateways — features/gateways/page.py
    # /chats — features/chat_channels/page.py
]


def _make_stub_page(
    router: APIRouter,
    rel_path: str,
    active_path: str,
    label: str,
    icon: str,
    *,
    detail: str,
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
                ui.label(detail).classes("text-sm opacity-40 mb-2")


def register_stub_pages(router: APIRouter) -> None:
    """Register Coming soon pages for routes not yet built in v2."""
    _default_detail = "This page will be implemented in a later phase."
    for spec in _STUBS:
        if len(spec) == 5:
            rel_path, nav_path, label, icon, detail = spec
        else:
            rel_path, nav_path, label, icon = spec
            detail = _default_detail
        _make_stub_page(
            router, rel_path, nav_path, label, icon, detail=detail
        )
