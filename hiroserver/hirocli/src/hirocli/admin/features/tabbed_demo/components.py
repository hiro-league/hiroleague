"""Tabbed demo components — one section per tab (guidelines §4, §1.6)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import ui

from hirocli.admin.shared.ui.data_table import data_table
from hirocli.admin.shared.ui.empty_state import empty_state


# ── Planets tab ──────────────────────────────────────────────

PLANET_COLUMNS: list[dict[str, Any]] = [
    {"name": "name", "label": "Planet", "field": "name", "align": "left", "sortable": True},
    {"name": "type", "label": "Type", "field": "type", "align": "left", "sortable": True},
    {"name": "diameter_km", "label": "Diameter (km)", "field": "diameter_km", "align": "right", "sortable": True},
    {"name": "moons", "label": "Moons", "field": "moons", "align": "right", "sortable": True},
    {"name": "actions", "label": "", "field": "actions", "align": "center"},
]


def planets_table(
    rows: list[dict[str, Any]],
    on_view_moons: Callable[[str], None],
) -> None:
    """Planet table with a 'View moons' action per row."""
    if not rows:
        empty_state(message="No planets match the current filter.", icon="public")
        return

    tbl = data_table(columns=PLANET_COLUMNS, rows=rows, row_key="id")
    tbl.add_slot(
        "body-cell-actions",
        """
        <q-td :props="props">
          <q-btn flat size="sm" icon="satellite_alt" class="q-ma-xs"
                 @click="() => $parent.$emit('view_moons', props.row)" />
        </q-td>
        """,
    )
    tbl.on("view_moons", lambda e: on_view_moons(e.args["id"]))


# ── Moons tab ────────────────────────────────────────────────

MOON_COLUMNS: list[dict[str, Any]] = [
    {"name": "name", "label": "Moon", "field": "name", "align": "left", "sortable": True},
    {"name": "diameter_km", "label": "Diameter (km)", "field": "diameter_km", "align": "right", "sortable": True},
    {"name": "discovery", "label": "Discovered", "field": "discovery", "align": "left", "sortable": True},
]


def moons_table(rows: list[dict[str, Any]], planet_filter: str | None) -> None:
    """Moon table, optionally filtered by planet."""
    if not rows:
        msg = f"No known moons for this planet." if planet_filter else "Select a planet to see its moons."
        empty_state(message=msg, icon="satellite_alt")
        return
    data_table(columns=MOON_COLUMNS, rows=rows, row_key="id")
