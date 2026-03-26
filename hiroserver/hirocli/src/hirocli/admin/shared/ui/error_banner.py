"""Inline error message with optional retry.

Guidelines §4 prefer Quasar QBanner; `ui.card` keeps Phase 0 simple and theme-safe.
Switch to `ui.element('q-banner')` if we need native banner behavior.
"""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui


def error_banner(
    *,
    message: str,
    detail: str | None = None,
    on_retry: Callable[[], None] | None = None,
) -> None:
    """Show a negative-styled banner; optional detail label and retry button."""
    with ui.card().classes("w-full border border-negative"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("error").classes("text-negative")
            ui.label(message).classes("text-negative font-medium")
        if detail:
            ui.label(detail).classes("text-xs opacity-70 ml-8")
        if on_retry:
            with ui.row().classes("justify-end w-full mt-2"):
                ui.button("Retry", on_click=on_retry).props("flat dense color=primary")
