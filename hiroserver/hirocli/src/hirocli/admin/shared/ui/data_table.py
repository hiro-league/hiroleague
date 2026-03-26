"""Thin wrapper around Quasar QTable for consistent defaults."""

from __future__ import annotations

from typing import Any

from nicegui import ui


def data_table(
    *,
    columns: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    row_key: str = "id",
) -> ui.table:
    """Create a full-width sortable table with standard styling."""
    return ui.table(columns=columns, rows=rows, row_key=row_key).classes("w-full")
