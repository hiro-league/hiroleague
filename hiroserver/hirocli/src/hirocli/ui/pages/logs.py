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
- Optional right-hand detail panel (header toggle): spans the full page height
  as a sibling of the content column; row click fills fields; Extra values and
  Message are pretty-printed when they parse as JSON or Python literals
  (CSV extras use ``repr()`` from the file sink, not strict JSON).
- All preferences persisted in nicegui_app.storage.user
"""

from __future__ import annotations

from nicegui import app as nicegui_app, ui

from hirocli.ui import state
from hirocli.ui.app import create_page_layout
from hirocli.ui.pages.logs_controller import LogsPageController
from hirocli.ui.pages.logs_detail import fill_detail_panel
from hirocli.ui.pages.logs_filters import (
    build_controls_row,
    build_level_filter_row,
    build_source_filter_row,
)
from hirocli.ui.pages.logs_grid import (
    COL_DEFS,
    LEVELS,
    row_passes_filters,
    set_chip_off,
    set_chip_on,
)
from hirocli.ui.pages.logs_styles import LOG_COLORS_CSS

_POLL_INTERVAL = 0.5   # seconds between incremental polls
_INITIAL_LINES = 500   # lines loaded on first open


@ui.page("/logs")
def logs_page() -> None:
    create_page_layout(active_path="/logs")
    ui.add_head_html(LOG_COLORS_CSS)

    # Top-level row: [content column | detail panel] — full page height minus admin header.
    # Elements are created inside a content column, then .move()'d into page_row
    # so the detail panel becomes a page-level sibling spanning the full height.
    page_row = ui.row().classes(
        "w-full items-stretch flex-nowrap gap-0 h-[calc(100vh-40px)]"
    )
    with ui.column().classes("flex-1 min-w-0 gap-3 p-6 overflow-y-auto") as content_col:
        if state.log_dir is None:
            ui.label("Logs").classes("text-2xl font-semibold")
            with ui.card().classes("w-full max-w-sm"):
                with ui.row().classes("items-center gap-3 p-2"):
                    ui.icon("article").classes("text-3xl opacity-30")
                    ui.label("Log directory not available.").classes("text-sm opacity-50")
            content_col.move(page_row)
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
            "level_filter": list(prefs.get("logs_level_filter", LEVELS[:])),
            "search_text": prefs.get("logs_search_text", ""),
            "auto_scroll": True,
            "selected_ids": set(),
            "detail_row": None,
            "detail_panel_open": bool(prefs.get("logs_detail_panel_open", False)),
        }

        # -------------------------------------------------------------------
        # Controller — created early so its methods can be passed directly
        # as callbacks to the filter-row builders below. bind_refs and
        # bind_grid are called once each layout element exists.
        # -------------------------------------------------------------------
        ctrl = LogsPageController(initial_state=_s)

        from hirocli.tools.logs import LogTailTool

        # -------------------------------------------------------------------
        # Pre-load initial data BEFORE creating the grid so rowData is
        # present at construction time (avoids update-before-mount issues).
        # -------------------------------------------------------------------
        initial_rows: list[dict] = []
        try:
            result = LogTailTool().execute(
                source="all",
                lines=_INITIAL_LINES,
                workspace=nicegui_app.storage.user.get("selected_workspace"),
            )
            _s["file_offsets"] = result.file_offsets
            initial_rows = [
                r for r in result.rows
                if row_passes_filters(r, _s["active_sources"], _s["active_channels"], _s["level_filter"])
            ]
            _s["row_data"] = initial_rows[:]
        except Exception:
            pass

        # -------------------------------------------------------------------
        # Page title + detail panel toggle
        # -------------------------------------------------------------------
        with ui.row().classes("w-full items-center justify-between gap-2 flex-wrap"):
            ui.label("Logs").classes("text-2xl font-semibold")
            detail_toggle_btn = ui.button(
                "Log details",
                icon="view_sidebar",
            ).props("dense outline rounded")
            if _s["detail_panel_open"]:
                set_chip_on(detail_toggle_btn)
            else:
                set_chip_off(detail_toggle_btn)

        # -------------------------------------------------------------------
        # Filter rows + controls (built by logs_filters helpers)
        # -------------------------------------------------------------------
        _src_refs = build_source_filter_row(
            _s["active_sources"], has_gateway, has_cli, on_toggle=ctrl.on_source_toggle,
        )
        build_level_filter_row(_s["level_filter"], on_change=ctrl.on_level_change)

        ctrl_refs = build_controls_row(
            search_text=_s["search_text"],
            sort_order=_s["sort_order"],
            paused=_s["paused"],
            auto_scroll=_s["auto_scroll"],
            available_channels=available_channels,
            active_channels=_s["active_channels"],
            channels_visible="channels" in _s["active_sources"],
            on_channel_change=ctrl.on_channel_change,
        )
        ctrl.bind_refs(ctrl_refs)

        # -------------------------------------------------------------------
        # AG Grid — fills available width inside the content column.
        # -------------------------------------------------------------------
        _grid_h = "h-[calc(100vh-340px)] min-h-48"
        grid_opts: dict = {
            "columnDefs": COL_DEFS,
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
            grid_opts, html_columns=[4, 5, 6, 7],
        ).classes(f"w-full {_grid_h}")
        ctrl.bind_grid(grid)

        # -------------------------------------------------------------------
        # Detail panel — created here then moved to page_row so it spans the
        # full page height as a sibling of the content column.
        # -------------------------------------------------------------------
        _detail_base = "log-detail-panel w-[min(100%,420px)] shrink-0 flex flex-col"
        _detail_classes = (
            _detail_base if _s["detail_panel_open"]
            else f"{_detail_base} hidden"
        )
        detail_outer = ui.column().classes(_detail_classes)
        with detail_outer:
            with ui.row().classes(
                "log-detail-panel-header w-full items-center justify-between gap-2"
            ):
                ui.label("Log line").classes("text-sm font-semibold")
                close_detail_btn = ui.button(icon="close").props("flat dense round")
            detail_body = ui.column().classes("log-detail-body w-full gap-0")

        # Move content column and detail panel into the page-level row
        content_col.move(page_row)
        detail_outer.move(page_row)

        ctrl.bind_detail(detail_outer, detail_toggle_btn, detail_body)
        detail_toggle_btn.on_click(
            lambda: ctrl.set_detail_panel_open(not _s["detail_panel_open"])
        )
        close_detail_btn.on_click(lambda: ctrl.set_detail_panel_open(False))

        if _s["detail_panel_open"]:
            fill_detail_panel(detail_body, _s.get("detail_row"))

        grid.on("selectionChanged", ctrl.on_selection_changed)
        grid.on("cellClicked", ctrl.on_cell_clicked)

        # -------------------------------------------------------------------
        # Wire control bar handlers and start polling timer
        # -------------------------------------------------------------------
        ctrl_refs.search_input.on_value_change(ctrl.on_search)
        ctrl_refs.sort_btn.on_click(ctrl.toggle_sort)
        ctrl_refs.auto_scroll_btn.on_click(ctrl.toggle_auto_scroll)

        poll_timer = ui.timer(_POLL_INTERVAL, ctrl.poll)
        poll_timer.active = not _s["paused"]
        ctrl.poll_timer = poll_timer
        ctrl_refs.pause_btn.on_click(ctrl.toggle_pause)

        # -------------------------------------------------------------------
        # Apply saved sort after grid is mounted (deferred so the AG Grid
        # API is available on the client side).
        # -------------------------------------------------------------------
        ui.timer(0.1, ctrl.apply_sort, once=True)
