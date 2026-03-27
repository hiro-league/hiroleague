"""Reusable destructive / confirmation dialog."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nicegui import ui


@dataclass(frozen=True)
class ConfirmDialogHandles:
    """References so callers can update title/message before ``dialog.open()``."""

    dialog: ui.dialog
    title_label: ui.label
    message_label: ui.label


def confirm_dialog(
    *,
    title: str,
    message: str,
    confirm_label: str = "Confirm",
    cancel_label: str = "Cancel",
    confirm_icon: str | None = None,
    on_confirm: Callable[[], object],
) -> ConfirmDialogHandles:
    """Build a modal with cancel + confirm. Caller must open with ``dialog.open()``.

    If ``on_confirm`` (sync or async) returns exactly ``False``, the dialog stays open
    (e.g. validation or server error). Any other return closes the dialog after the handler runs.
    """
    dialog = ui.dialog()

    async def _run_confirm() -> None:
        result = on_confirm()
        if inspect.isawaitable(result):
            result = await result
        if result is False:
            return
        dialog.close()

    with dialog, ui.card().classes("w-96"):
        title_label = ui.label(title).classes("text-lg font-semibold mb-2")
        message_label = ui.label(message).classes("text-sm opacity-80")
        with ui.row().classes("justify-end gap-2 w-full mt-4"):
            ui.button(cancel_label, on_click=dialog.close).props("flat")
            btn_kwargs: dict[str, Any] = {"on_click": _run_confirm}
            if confirm_icon:
                btn_kwargs["icon"] = confirm_icon
            ui.button(confirm_label, **btn_kwargs).props("color=negative")

    return ConfirmDialogHandles(dialog=dialog, title_label=title_label, message_label=message_label)
