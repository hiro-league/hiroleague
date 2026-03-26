"""AG Grid column definitions and log-level chip helpers for the admin Logs page.

Level and Module columns display pre-rendered HTML (via html_columns on the
grid) pointing to *_html fields. NiceGUI's AG Grid does NOT reliably apply
cellStyle {"function":...} or cellClassRules — html_columns is the only
approach that works for per-cell dynamic colouring.
"""

from __future__ import annotations

import json

from nicegui import ui

# ---------------------------------------------------------------------------
# AG Grid column definitions.
# Fixed widths for most columns; Extra uses flex:1 to fill remaining space
# (safe because autoSizeStrategy is disabled in grid options).
# ---------------------------------------------------------------------------
COL_DEFS: list[dict] = [
    {
        # Hidden sort key — epoch float (e.g. 1742312005.437821) stored as a
        # number in rowData so AG Grid's default numeric comparator applies.
        # Sub-second precision ensures correct ordering even within the same
        # second. Sort targets colId "timestamp".
        "field": "timestamp",
        "hide": True,
        "sortable": True,
    },
    {
        "headerName": "Date",
        "field": "date_display",
        "width": 72,
        "sortable": False,
        "filter": True,
        "resizable": True,
    },
    {
        "headerName": "Time",
        "field": "timestamp_display",
        "width": 110,
        "sortable": False,             # sort driven by hidden timestamp column
        "filter": True,
        "resizable": True,
        "cellStyle": {"textAlign": "right"},
    },
    {
        "headerName": "Source",
        "field": "source",
        "width": 130,
        "sortable": True,
        "filter": True,
        "resizable": True,
    },
    {
        "headerName": "Module",
        "field": "module_html",
        "width": 120,
        "sortable": True,
        "resizable": True,
    },
    {
        "headerName": "Lvl",
        "field": "level_html",
        "width": 80,
        "sortable": True,
        "resizable": True,
    },
    {
        "headerName": "Message",
        # message_html renders startup rows with a neutral highlight via html_columns.
        # Raw `message` field is kept for server-side search; AG Grid column filter
        # is disabled here because it would match against HTML markup.
        "field": "message_html",
        "tooltipField": "message",  # tooltip shows raw text, not HTML markup
        "width": 400,
        "sortable": False,
        "filter": False,
        "resizable": True,
    },
    {
        "headerName": "Extra",
        "field": "extra_html",
        "tooltipField": "extra_tooltip_html",
        "flex": 1,          # fills remaining table width; safe with autoSizeStrategy: null
        "minWidth": 150,
        "sortable": True,
        # Sort/filter use raw ``extra``; html field would compare markup / match tags.
        ":comparator": (
            "(valueA, valueB, nodeA, nodeB) => { "
            "const ax = String(nodeA.data.extra ?? ''); "
            "const bx = String(nodeB.data.extra ?? ''); "
            "if (ax < bx) return -1; if (ax > bx) return 1; return 0; "
            "}"
        ),
        # Default AG Grid tooltip uses textContent, so HTML would show as escaped text.
        # This component renders pre-escaped markup from the server (log CSV only).
        ":tooltipComponent": (
            "(class { init(params) { "
            "this.eGui = document.createElement('div'); "
            "this.eGui.className = 'ag-tooltip'; "
            "const v = params.value; "
            "this.eGui.innerHTML = (v == null || v === '') ? '' : String(v); "
            "} getGui() { return this.eGui; } })"
        ),
        "filter": False,
        "resizable": True,
    },
]

LEVELS: list[str] = ["DEBUG", "FINEINFO", "INFO", "WARNING", "ERROR", "CRITICAL"]

LEVEL_CHIP_COLORS: dict[str, str] = {
    "DEBUG": "blue",
    "FINEINFO": "cyan",
    "INFO": "positive",
    "WARNING": "warning",
    "ERROR": "negative",
    "CRITICAL": "purple",
}


def set_chip_on(btn: ui.button) -> None:
    """Visually activate a chip button (filled appearance)."""
    btn.props(remove="flat")


def set_chip_off(btn: ui.button) -> None:
    """Visually deactivate a chip button (flat/outline appearance)."""
    btn.props(add="flat")


def apply_sort(grid: ui.aggrid, sort_order: str) -> None:
    """Apply timestamp sort to *grid* based on *sort_order* ('newest' or 'oldest')."""
    direction = "desc" if sort_order == "newest" else "asc"
    grid.run_grid_method(
        "applyColumnState",
        {
            "state": [{"colId": "timestamp", "sort": direction}],
            "defaultState": {"sort": None},
        },
    )


def scroll_to_edge(grid: ui.aggrid, row_count: int, sort_order: str) -> None:
    """Scroll *grid* to the leading edge (newest or oldest row depending on sort)."""
    if row_count == 0:
        return
    try:
        if sort_order == "newest":
            grid.run_grid_method("ensureIndexVisible", 0, "top")
        else:
            grid.run_grid_method("ensureIndexVisible", row_count - 1, "bottom")
    except Exception:
        pass


def restore_selection(grid: ui.aggrid, ids: set[str]) -> None:
    """Re-select rows by id after a grid.update() that cleared selection."""
    if not ids:
        return
    ids_json = json.dumps(list(ids))
    ui.run_javascript(
        f"const ids = new Set({ids_json});"
        f"getElement({grid.id}).api.forEachNode(n => {{"
        f"  if (ids.has(n.data.id)) n.setSelected(true);"
        f"}});"
    )


def row_passes_filters(
    row: dict,
    active_sources: list[str],
    active_channels: list[str],
    level_filter: list[str],
) -> bool:
    """Return True if *row* matches the current source / channel / level filters."""
    src = row.get("source", "")
    if src == "server" and "server" not in active_sources:
        return False
    if src.startswith("channel-"):
        if "channels" not in active_sources:
            return False
        channel_name = src.removeprefix("channel-")
        if active_channels and channel_name not in active_channels:
            return False
    if src == "gateway" and "gateway" not in active_sources:
        return False
    if src == "cli" and "cli" not in active_sources:
        return False
    if level_filter and row.get("level") not in level_filter:
        return False
    return True
