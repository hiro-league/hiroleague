"""Prominent warning block using Quasar semantic colors (guidelines §3.3 — no fixed amber palette)."""

from __future__ import annotations

from nicegui import ui


def warning_callout(*, message: str) -> None:
    """Border + warning-colored icon; body text uses default theme foreground for contrast."""
    with ui.card().classes("w-full border border-warning"):
        with ui.row().classes("items-start gap-2 p-1"):
            ui.icon("warning").classes("text-warning text-xl mt-0.5 shrink-0")
            ui.label(message).classes("text-sm")
