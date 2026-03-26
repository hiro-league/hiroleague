"""Loading placeholder for async sections."""

from __future__ import annotations

from nicegui import ui


def loading_state(*, message: str = "Loading…") -> None:
    with ui.row().classes("items-center gap-3 p-4"):
        ui.spinner(size="md")
        ui.label(message).classes("text-sm opacity-70")
