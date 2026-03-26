"""Empty list / no-data placeholder."""

from __future__ import annotations

from nicegui import ui


def empty_state(*, message: str, icon: str = "inbox") -> None:
    with ui.card().classes("w-full items-center text-center py-8"):
        ui.icon(icon).classes("text-5xl opacity-30")
        ui.label(message).classes("text-sm opacity-60 mt-2")
