"""Logs page — unified AG Grid log viewer.

Single table merging server.log, channel-*.log, cli.log, and gateway.log.
Filtering: source chips (Server / Channels / CLI / Gateway) with channel
multi-select, level chips, full-text search (server-side via LogSearchTool).
Live tailing: LogTailTool with incremental byte-offset polling.

Features:
- Theme-aware colors: CSS variables switch with Quasar dark mode
- Newest-first / Oldest-first toggle with smart auto-scroll
  (auto-scroll only while pinned to the leading edge; suspends when
  the user scrolls away, resumes when they scroll back to the edge)
- All preferences persisted in nicegui_app.storage.user
"""

from __future__ import annotations

import json

from nicegui import app as nicegui_app, ui

from hirocli.ui import state
from hirocli.ui.app import create_page_layout

_POLL_INTERVAL = 0.5   # seconds between incremental polls
_INITIAL_LINES = 500   # lines loaded on first open

# ---------------------------------------------------------------------------
# Theme-aware CSS for log level and module colours.
#
# cellStyle {"function": "..."} does not apply in NiceGUI's AG Grid wrapper,
# so colours are driven by cellClassRules (plain boolean expressions that AG
# Grid evaluates natively) + CSS classes defined here.
# ---------------------------------------------------------------------------
_LOG_COLORS_CSS = """
<style>
/* Level colours — light mode */
.log-lvl-debug    { color: #3b82f6 !important; }
.log-lvl-fineinfo { color: #0891b2 !important; }
.log-lvl-info     { color: #16a34a !important; }
.log-lvl-warning  { color: #ca8a04 !important; font-weight: bold; }
.log-lvl-error    { color: #dc2626 !important; font-weight: bold; }
.log-lvl-critical { color: #9333ea !important; font-weight: bold; }

/* Module colours — light mode (hash bucket 0-3) */
.log-mod-0 { color: #0891b2 !important; }
.log-mod-1 { color: #c026d3 !important; }
.log-mod-2 { color: #ca8a04 !important; }
.log-mod-3 { color: #16a34a !important; }

/* Dark-mode overrides */
.body--dark .log-lvl-debug    { color: #60a5fa !important; }
.body--dark .log-lvl-fineinfo { color: #22d3ee !important; }
.body--dark .log-lvl-info     { color: #4ade80 !important; }
.body--dark .log-lvl-warning  { color: #facc15 !important; }
.body--dark .log-lvl-error    { color: #f87171 !important; }
.body--dark .log-lvl-critical { color: #c084fc !important; }

.body--dark .log-mod-0 { color: #22d3ee !important; }
.body--dark .log-mod-1 { color: #e879f9 !important; }
.body--dark .log-mod-2 { color: #fde047 !important; }
.body--dark .log-mod-3 { color: #86efac !important; }

/* Startup row — neutral slate tint applied to every cell in the row.
   rowClassRules adds "log-startup-row" to the AG Grid row element when
   data.is_startup is true; targeting .ag-cell fills all columns. */
.log-startup-row .ag-cell { background-color: rgba(203, 213, 225, 0.35) !important; }
.body--dark .log-startup-row .ag-cell { background-color: rgba(71, 85, 105, 0.35) !important; }

/* Message text in startup rows — semi-bold for extra visual weight */
.log-startup-msg { font-weight: 600; }

/* Extra column — muted debug colour */
:root  { --log-debug: #3b82f6; }
.body--dark { --log-debug: #60a5fa; }

/* Tooltip styling — wrap long cell values nicely */
.ag-tooltip {
    max-width: 500px !important;
    white-space: pre-wrap !important;
    word-break: break-word !important;
    padding: 8px 12px !important;
    font-size: 12px !important;
    line-height: 1.4 !important;
}
</style>
"""

# ---------------------------------------------------------------------------
# AG Grid column definitions.
# Fixed widths for most columns; Extra uses flex:1 to fill remaining space
# (safe because autoSizeStrategy is disabled in grid options).
#
# Level and Module columns display pre-rendered HTML (via html_columns on the
# grid) pointing to *_html fields. NiceGUI's AG Grid does NOT reliably apply
# cellStyle {"function":...} or cellClassRules — html_columns is the only
# approach that works for per-cell dynamic colouring.
# ---------------------------------------------------------------------------
_COL_DEFS = [
    {
        # Hidden sort key — epoch float (e.g. 1742312005.437821) stored as a
        # number in rowData so AG Grid's default numeric comparator applies.
        # Sub-second precision ensures correct ordering even within the same
        # second. _apply_sort() targets colId "timestamp".
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
        "field": "extra",
        "tooltipField": "extra",
        "flex": 1,          # fills remaining table width; safe with autoSizeStrategy: null
        "minWidth": 150,
        "sortable": True,
        "filter": True,
        "resizable": True,
        "cellStyle": {"color": "var(--log-debug)", "opacity": "0.75"},
    },
]

_LEVELS = ["DEBUG", "FINEINFO", "INFO", "WARNING", "ERROR", "CRITICAL"]
_LEVEL_CHIP_COLORS = {
    "DEBUG": "blue",
    "FINEINFO": "cyan",
    "INFO": "positive",
    "WARNING": "warning",
    "ERROR": "negative",
    "CRITICAL": "purple",
}


def _set_chip_on(btn: ui.button) -> None:
    """Visually activate a chip button (filled appearance)."""
    btn.props(remove="flat")

def _set_chip_off(btn: ui.button) -> None:
    """Visually deactivate a chip button (flat/outline appearance)."""
    btn.props(add="flat")


@ui.page("/logs")
def logs_page() -> None:
    create_page_layout(active_path="/logs")
    ui.add_head_html(_LOG_COLORS_CSS)

    with ui.column().classes("w-full gap-3 p-6"):
        ui.label("Logs").classes("text-2xl font-semibold")

        if state.log_dir is None:
            with ui.card().classes("w-full max-w-sm"):
                with ui.row().classes("items-center gap-3 p-2"):
                    ui.icon("article").classes("text-3xl opacity-30")
                    ui.label("Log directory not available.").classes("text-sm opacity-50")
            return

        log_dir = state.log_dir
        # state.gateway_log_dir is set once at startup in run_admin_ui; fall back
        # to dynamic resolution so gateway logs still appear if the startup
        # resolution failed silently.
        gw_log_dir = state.gateway_log_dir
        if gw_log_dir is None:
            from hirocli.tools.logs import _resolve_gateway_log_dir
            gw_log_dir = _resolve_gateway_log_dir()

        available_channels: list[str] = [
            f.stem.removeprefix("channel-")
            for f in sorted(log_dir.glob("channel-*.log"))
        ]
        has_gateway = gw_log_dir is not None and (gw_log_dir / "gateway.log").exists()
        has_cli = (log_dir / "cli.log").exists()

        # -------------------------------------------------------------------
        # Restore persisted preferences (fall back to sensible defaults).
        # -------------------------------------------------------------------
        prefs = nicegui_app.storage.user
        _default_sources = (
            ["server", "channels"]
            + (["gateway"] if has_gateway else [])
            + (["cli"] if has_cli else [])
        )
        _default_channels = available_channels[:]

        _s: dict = {
            "file_offsets": {},
            "row_data": [],
            "is_search_mode": False,
            "paused": prefs.get("logs_paused", False),
            "sort_order": prefs.get("logs_sort_order", "newest"),
            "active_sources": list(prefs.get("logs_sources", _default_sources)),
            "active_channels": list(prefs.get("logs_channels", _default_channels)),
            "level_filter": list(prefs.get("logs_level_filter", _LEVELS[:])),
            "search_text": prefs.get("logs_search_text", ""),
            "auto_scroll": True,
            "selected_ids": set(),
        }

        from hirocli.tools.logs import LogSearchTool, LogTailTool

        def _workspace() -> str | None:
            return nicegui_app.storage.user.get("selected_workspace")

        # -------------------------------------------------------------------
        # Filtering helpers
        # -------------------------------------------------------------------
        def _row_passes_filters(row: dict) -> bool:
            src = row.get("source", "")
            active = _s["active_sources"]
            if src == "server" and "server" not in active:
                return False
            if src.startswith("channel-"):
                if "channels" not in active:
                    return False
                channel_name = src.removeprefix("channel-")
                if _s["active_channels"] and channel_name not in _s["active_channels"]:
                    return False
            if src == "gateway" and "gateway" not in active:
                return False
            if src == "cli" and "cli" not in active:
                return False
            if _s["level_filter"] and row.get("level") not in _s["level_filter"]:
                return False
            return True

        # -------------------------------------------------------------------
        # Pre-load initial data BEFORE creating the grid so rowData is
        # present at construction time (avoids update-before-mount issues).
        # -------------------------------------------------------------------
        initial_rows: list[dict] = []
        try:
            result = LogTailTool().execute(
                source="all",
                lines=_INITIAL_LINES,
                workspace=_workspace(),
            )
            _s["file_offsets"] = result.file_offsets
            initial_rows = [r for r in result.rows if _row_passes_filters(r)]
            _s["row_data"] = initial_rows[:]
        except Exception:
            pass

        # Channel filter elements are placed in the controls row below;
        # declare references here so source-chip closures can reach them.
        _channel_label: ui.label | None = None
        _channel_select: ui.select | None = None

        # -------------------------------------------------------------------
        # Source filter row
        # -------------------------------------------------------------------
        with ui.row().classes("items-center gap-2 flex-wrap"):
            ui.label("Source:").classes("text-sm font-medium opacity-60 self-center")
            _src_btns: dict[str, ui.button] = {}

            def _make_source_btn(name: str, label: str) -> None:
                is_on = name in _s["active_sources"]
                btn = ui.button(label).props("dense rounded").classes("text-xs")
                if not is_on:
                    _set_chip_off(btn)
                _src_btns[name] = btn

                def _on_click(n=name, b=btn) -> None:
                    if n in _s["active_sources"]:
                        _s["active_sources"] = [s for s in _s["active_sources"] if s != n]
                        _set_chip_off(b)
                    else:
                        _s["active_sources"].append(n)
                        _set_chip_on(b)
                    prefs["logs_sources"] = _s["active_sources"]
                    channels_visible = "channels" in _s["active_sources"]
                    if _channel_label:
                        _channel_label.set_visibility(channels_visible)
                    if _channel_select:
                        _channel_select.set_visibility(channels_visible)
                    _schedule_reload()

                btn.on_click(_on_click)

            _make_source_btn("server", "Server")
            _make_source_btn("channels", "Channels")
            if has_gateway:
                _make_source_btn("gateway", "Gateway")
            if has_cli:
                _make_source_btn("cli", "CLI")

        # -------------------------------------------------------------------
        # Level filter row
        # -------------------------------------------------------------------
        with ui.row().classes("items-center gap-2 flex-wrap"):
            ui.label("Level:").classes("text-sm font-medium opacity-60 self-center")
            _lvl_btns: dict[str, ui.button] = {}

            def _make_level_btn(lvl: str) -> None:
                is_on = lvl in _s["level_filter"]
                color = _LEVEL_CHIP_COLORS.get(lvl, "grey")
                btn = ui.button(lvl).props(f"dense rounded color={color}").classes("text-xs")
                if not is_on:
                    _set_chip_off(btn)
                _lvl_btns[lvl] = btn

                def _on_click(l=lvl, b=btn) -> None:
                    if l in _s["level_filter"]:
                        _s["level_filter"] = [x for x in _s["level_filter"] if x != l]
                        _set_chip_off(b)
                    else:
                        _s["level_filter"].append(l)
                        _set_chip_on(b)
                    prefs["logs_level_filter"] = _s["level_filter"]
                    _schedule_reload()

                btn.on_click(_on_click)

            for _lvl in _LEVELS:
                _make_level_btn(_lvl)

        # -------------------------------------------------------------------
        # Controls row: search | sort | pause | auto-scroll | channel filter
        # -------------------------------------------------------------------
        with ui.row().classes("items-center gap-3 flex-wrap"):
            search_input = (
                ui.input(placeholder="Search logs…", value=_s["search_text"])
                .classes("min-w-64")
                .props("dense outlined clearable")
            )

            sort_btn = ui.button(
                "Newest first" if _s["sort_order"] == "newest" else "Oldest first",
                icon="swap_vert",
            ).props("flat dense outlined")

            pause_btn = ui.button(
                "Resume" if _s["paused"] else "Pause",
                icon="play_arrow" if _s["paused"] else "pause",
            ).props("flat dense outlined")

            auto_scroll_btn = ui.button(
                "Auto-scroll on",
                icon="vertical_align_bottom",
            ).props("flat dense outlined")
            auto_scroll_btn.classes("text-positive" if _s["auto_scroll"] else "opacity-50")

            # Channel filter inline — only shown when Channels source is active.
            if available_channels:
                _channel_label = ui.label("Channel:").classes("text-sm opacity-50 self-center")
                _channel_select = (
                    ui.select(
                        available_channels,
                        multiple=True,
                        value=_s["active_channels"] or available_channels,
                        label="",
                    )
                    .classes("min-w-32 max-w-60")
                    .props("dense outlined")
                )

                def _on_channel_change(e) -> None:
                    _s["active_channels"] = list(e.value or [])
                    prefs["logs_channels"] = _s["active_channels"]
                    _schedule_reload()

                _channel_select.on_value_change(_on_channel_change)

                channels_on = "channels" in _s["active_sources"]
                _channel_label.set_visibility(channels_on)
                _channel_select.set_visibility(channels_on)

        # -------------------------------------------------------------------
        # AG Grid — created with pre-loaded rowData.
        # -------------------------------------------------------------------
        grid_opts: dict = {
            "columnDefs": _COL_DEFS,
            "rowData": initial_rows,
            "defaultColDef": {"resizable": True, "sortable": True, "filter": True},
            "rowSelection": "multiple",
            "animateRows": False,
            "rowHeight": 24,
            "headerHeight": 28,
            "suppressHorizontalScroll": False,
            # Disable NiceGUI's default autoSizeStrategy — it re-triggers on every
            # grid.update() call and causes columns to resize on each new row/filter.
            # Columns use explicit width values so auto-sizing is not needed.
            "autoSizeStrategy": None,
            # AG Grid evaluates expression strings in rowClassRules using `data.*`
            # variables from the row's data object — this is native AG Grid behaviour
            # and works without any JS function wrapper.
            "rowClassRules": {"log-startup-row": "data.is_startup"},
            "tooltipShowDelay": 300,
            "tooltipInteraction": True,
        }
        grid = ui.aggrid(
            grid_opts, html_columns=[4, 5, 6],
        ).classes("w-full h-[calc(100vh-340px)] min-h-48")

        # -------------------------------------------------------------------
        # Selection persistence — track selected row IDs so they survive
        # grid.update() calls (which reset AG Grid's internal selection).
        # -------------------------------------------------------------------

        async def _on_selection_changed(_e) -> None:
            selected = await grid.get_selected_rows()
            _s["selected_ids"] = {r["id"] for r in selected} if selected else set()

        grid.on("selectionChanged", _on_selection_changed)

        def _restore_selection(ids: set[str]) -> None:
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

        # -------------------------------------------------------------------
        # Data helpers
        # -------------------------------------------------------------------

        def _schedule_reload() -> None:
            _reload_initial()

        def _reload_initial() -> None:
            _s["file_offsets"] = {}
            if _s["search_text"]:
                _s["is_search_mode"] = True
                _do_search(_s["search_text"])
                return
            _s["is_search_mode"] = False
            try:
                result = LogTailTool().execute(
                    source="all",
                    lines=_INITIAL_LINES,
                    workspace=_workspace(),
                )
                _s["file_offsets"] = result.file_offsets
                rows = [r for r in result.rows if _row_passes_filters(r)]
                _set_grid_data(rows)
            except Exception:
                pass

        def _do_search(query: str) -> None:
            try:
                result = LogSearchTool().execute(
                    source="all",
                    query=query,
                    workspace=_workspace(),
                )
                rows = [r for r in result.rows if _row_passes_filters(r)]
                _set_grid_data(rows)
            except Exception:
                pass

        def _set_grid_data(rows: list[dict]) -> None:
            # Snapshot selected IDs before grid.update() clears selection.
            saved_ids = set(_s["selected_ids"])
            _s["row_data"] = rows
            grid.options["rowData"] = rows
            grid.update()
            # grid.update() resets AG Grid column state — re-apply sort.
            _apply_sort()
            _restore_selection(saved_ids)
            if _s["auto_scroll"]:
                _scroll_to_edge()

        def _append_rows(rows: list[dict]) -> None:
            if not rows:
                return
            _s["row_data"].extend(rows)
            # applyTransaction adds rows without replacing existing data,
            # so AG Grid column state, sort order, and selection are preserved.
            # Do NOT assign grid.options["rowData"] here — NiceGUI's reactive
            # sync would push a full rowData replace to the client, duplicating
            # the rows and resetting sort. _set_grid_data handles the full sync.
            grid.run_grid_method("applyTransaction", {"add": rows})
            if _s["auto_scroll"]:
                _scroll_to_edge()

        def _scroll_to_edge() -> None:
            count = len(_s["row_data"])
            if count == 0:
                return
            try:
                if _s["sort_order"] == "newest":
                    grid.run_grid_method("ensureIndexVisible", 0, "top")
                else:
                    grid.run_grid_method("ensureIndexVisible", count - 1, "bottom")
            except Exception:
                pass

        def _apply_sort() -> None:
            direction = "desc" if _s["sort_order"] == "newest" else "asc"
            grid.run_grid_method(
                "applyColumnState",
                {
                    "state": [{"colId": "timestamp", "sort": direction}],
                    "defaultState": {"sort": None},
                },
            )

        # -------------------------------------------------------------------
        # Control event handlers
        # -------------------------------------------------------------------
        def _on_search(e) -> None:
            text = (e.value or "").strip() if hasattr(e, "value") else ""
            _s["search_text"] = text
            prefs["logs_search_text"] = text
            if text:
                _s["is_search_mode"] = True
                _do_search(text)
            else:
                _s["is_search_mode"] = False
                _s["file_offsets"] = {}
                _reload_initial()

        search_input.on_value_change(_on_search)

        def _toggle_sort() -> None:
            _s["sort_order"] = "oldest" if _s["sort_order"] == "newest" else "newest"
            prefs["logs_sort_order"] = _s["sort_order"]
            sort_btn.set_text("Newest first" if _s["sort_order"] == "newest" else "Oldest first")
            _apply_sort()

        sort_btn.on_click(_toggle_sort)

        def _toggle_pause() -> None:
            _s["paused"] = not _s["paused"]
            prefs["logs_paused"] = _s["paused"]
            if _s["paused"]:
                pause_btn.set_text("Resume")
                pause_btn.props("flat dense outlined icon=play_arrow")
            else:
                pause_btn.set_text("Pause")
                pause_btn.props("flat dense outlined icon=pause")
            poll_timer.active = not _s["paused"]

        pause_btn.on_click(_toggle_pause)

        def _toggle_auto_scroll() -> None:
            _s["auto_scroll"] = not _s["auto_scroll"]
            if _s["auto_scroll"]:
                auto_scroll_btn.set_text("Auto-scroll on")
                auto_scroll_btn.classes(remove="opacity-50")
                auto_scroll_btn.classes(add="text-positive")
            else:
                auto_scroll_btn.set_text("Auto-scroll off")
                auto_scroll_btn.classes(remove="text-positive")
                auto_scroll_btn.classes(add="opacity-50")

        auto_scroll_btn.on_click(_toggle_auto_scroll)

        # -------------------------------------------------------------------
        # Polling timer
        # -------------------------------------------------------------------
        def _poll() -> None:
            if _s["paused"] or _s["is_search_mode"]:
                return
            try:
                offsets_json = (
                    json.dumps(_s["file_offsets"]) if _s["file_offsets"] else None
                )
                result = LogTailTool().execute(
                    source="all",
                    after_offsets=offsets_json,
                    workspace=_workspace(),
                )
                _s["file_offsets"] = result.file_offsets
                new_rows = [r for r in result.rows if _row_passes_filters(r)]
                _append_rows(new_rows)
            except RuntimeError:
                pass
            except Exception:
                pass

        poll_timer = ui.timer(_POLL_INTERVAL, _poll)
        poll_timer.active = not _s["paused"]

        # -------------------------------------------------------------------
        # Apply saved sort after grid is mounted (deferred so the AG Grid
        # API is available on the client side).
        # -------------------------------------------------------------------
        ui.timer(0.1, _apply_sort, once=True)
