"""Multi-field form in a modal — guidelines §4 (non-standard layouts still use ui.dialog directly)."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from nicegui import ui

InputKind = Literal["text", "number", "password"]


@dataclass(frozen=True)
class FormField:
    """One row in the form: maps to ui.input or ui.number."""

    key: str
    label: str
    placeholder: str = ""
    kind: InputKind = "text"


def form_dialog(
    *,
    title: str,
    fields: Sequence[FormField],
    on_submit: Callable[[dict[str, Any]], object],
    submit_label: str = "Submit",
    cancel_label: str = "Cancel",
    card_classes: str = "w-96",
) -> ui.dialog:
    """Build a modal with dynamic fields. Caller opens with ``dialog.open()``.

    ``on_submit`` receives ``{field.key: value, ...}`` (str values from inputs; numbers as str
    from number widgets — parse in the callback). May be sync or async (awaited like
    ``confirm_dialog``).
    """
    dialog = ui.dialog()
    widgets: dict[str, Any] = {}

    with dialog, ui.card().classes(card_classes):
        ui.label(title).classes("text-lg font-semibold mb-2")
        for f in fields:
            if f.kind == "number":
                widgets[f.key] = ui.number(
                    f.label,
                    placeholder=f.placeholder or None,
                ).classes("w-full")
            else:
                inp = ui.input(
                    f.label,
                    placeholder=f.placeholder or None,
                ).classes("w-full")
                if f.kind == "password":
                    inp.props("type=password")
                widgets[f.key] = inp

        async def _run_submit() -> None:
            values: dict[str, Any] = {}
            for f in fields:
                w = widgets[f.key]
                values[f.key] = w.value
            result = on_submit(values)
            if inspect.isawaitable(result):
                await result
            dialog.close()

        with ui.row().classes("justify-end gap-2 w-full mt-4"):
            ui.button(cancel_label, on_click=dialog.close).props("flat")
            ui.button(submit_label, on_click=_run_submit).props("color=primary")

    return dialog
