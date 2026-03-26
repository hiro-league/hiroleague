"""Reusable destructive / confirmation dialog."""

from __future__ import annotations

import inspect
from collections.abc import Callable

from nicegui import ui


def confirm_dialog(
    *,
    title: str,
    message: str,
    confirm_label: str = "Confirm",
    cancel_label: str = "Cancel",
    on_confirm: Callable[[], object],
) -> ui.dialog:
    """Build a modal with cancel + confirm. Caller must open with dialog.open()."""
    dialog = ui.dialog()

    async def _run_confirm() -> None:
        result = on_confirm()
        if inspect.isawaitable(result):
            await result
        dialog.close()

    with dialog, ui.card().classes("w-96"):
        ui.label(title).classes("text-lg font-semibold mb-2")
        ui.label(message).classes("text-sm opacity-80")
        with ui.row().classes("justify-end gap-2 w-full mt-4"):
            ui.button(cancel_label, on_click=dialog.close).props("flat")
            ui.button(confirm_label, on_click=_run_confirm).props("color=negative")

    return dialog
