"""Dashboard-style metric card using Quasar semantic colors."""

from __future__ import annotations

from nicegui import ui


def stat_card(title: str, value: str, icon: str, *, ok: bool | None = None) -> None:
    """Single stat tile: icon, bold value, caption. ok tints value positive/negative."""
    value_classes = "text-2xl font-bold"
    if ok is True:
        value_classes += " text-positive"
    elif ok is False:
        value_classes += " text-negative"

    with ui.card().classes("w-full"):
        with ui.row().classes("items-start gap-3 p-1"):
            ui.icon(icon).classes("text-3xl opacity-50 mt-1")
            with ui.column().classes("gap-0"):
                ui.label(value).classes(value_classes)
                ui.label(title).classes("text-sm opacity-60")
