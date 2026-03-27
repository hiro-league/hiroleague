"""AG Grid column definitions and log-level helpers for admin logs (guidelines §1.1)."""

from __future__ import annotations

import json

from hiro_commons.log import Logger
from nicegui import ui

_log = Logger.get("ADMIN_LOGS_GRID")

COL_DEFS: list[dict] = [
    {
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
        "sortable": False,
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
        "field": "message_html",
        "tooltipField": "message",
        "width": 400,
        "sortable": False,
        "filter": False,
        "resizable": True,
    },
    {
        "headerName": "Extra",
        "field": "extra_html",
        "tooltipField": "extra_tooltip_html",
        "flex": 1,
        "minWidth": 150,
        "sortable": True,
        ":comparator": (
            "(valueA, valueB, nodeA, nodeB) => { "
            "const ax = String(nodeA.data.extra ?? ''); "
            "const bx = String(nodeB.data.extra ?? ''); "
            "if (ax < bx) return -1; if (ax > bx) return 1; return 0; "
            "}"
        ),
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
    btn.props(remove="flat")


def set_chip_off(btn: ui.button) -> None:
    btn.props(add="flat")


def apply_sort(grid: ui.aggrid, sort_order: str) -> None:
    direction = "desc" if sort_order == "newest" else "asc"
    grid.run_grid_method(
        "applyColumnState",
        {
            "state": [{"colId": "timestamp", "sort": direction}],
            "defaultState": {"sort": None},
        },
    )


def scroll_to_edge(grid: ui.aggrid, row_count: int, sort_order: str) -> None:
    if row_count == 0:
        return
    try:
        if sort_order == "newest":
            grid.run_grid_method("ensureIndexVisible", 0, "top")
        else:
            grid.run_grid_method("ensureIndexVisible", row_count - 1, "bottom")
    except Exception as exc:
        # Grid API may be unavailable briefly after update; avoid silent failure (guidelines §10).
        _log.debug(
            "⚠️ Logs grid auto-scroll skipped — ensureIndexVisible failed",
            error=str(exc),
            row_count=row_count,
            sort_order=sort_order,
        )


def restore_selection(grid: ui.aggrid, ids: set[str]) -> None:
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
