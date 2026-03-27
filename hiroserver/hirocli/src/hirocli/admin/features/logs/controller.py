"""Logs page controller — tab storage prefs, grid, tail/search via LogsService (guidelines §2.3)."""

from __future__ import annotations

from nicegui import app as nicegui_app, context, run, ui

from hirocli.admin.context import get_runtime_context, get_selected_workspace
from hirocli.admin.features.logs.components import (
    ControlsRefs,
    build_controls_row,
    build_level_filter_row,
    build_source_filter_row,
    fill_detail_panel,
)
from hirocli.admin.features.logs.grid import (
    COL_DEFS,
    LEVELS,
    apply_sort,
    restore_selection,
    row_passes_filters,
    scroll_to_edge,
    set_chip_off,
    set_chip_on,
)
from hirocli.admin.features.logs.service import LogsService
from hirocli.admin.shared.ui.error_banner import error_banner
from hirocli.admin.shared.ui.loading_state import loading_state

_POLL_INTERVAL = 0.5

# Tab storage keys (guidelines §2.2) — page prefs survive reload within the tab.
_K_PAUSED = "logs.paused"
_K_SORT = "logs.sort_order"
_K_SOURCES = "logs.sources"
_K_CHANNELS = "logs.channels"
_K_LEVELS = "logs.level_filter"
_K_SEARCH = "logs.search_text"
_K_DETAIL_OPEN = "logs.detail_panel_open"


class LogsPageController:
    """Owns mutable page state, grid wiring, and tail/search pipeline."""

    def __init__(self) -> None:
        self._service = LogsService()
        self.s: dict = {}
        self.grid: ui.aggrid | None = None
        self.ctrl_refs: ControlsRefs | None = None
        self.poll_timer: ui.timer | None = None
        self.detail_outer: ui.column | None = None
        self.detail_toggle_btn: ui.button | None = None
        self.detail_body: ui.column | None = None

    def _tab(self) -> dict:
        return nicegui_app.storage.tab

    @property
    def _workspace(self) -> str | None:
        return get_selected_workspace()

    def _persist_tab(self) -> None:
        t = self._tab()
        t[_K_PAUSED] = self.s["paused"]
        t[_K_SORT] = self.s["sort_order"]
        t[_K_SOURCES] = list(self.s["active_sources"])
        t[_K_CHANNELS] = list(self.s["active_channels"])
        t[_K_LEVELS] = list(self.s["level_filter"])
        t[_K_SEARCH] = self.s["search_text"]
        t[_K_DETAIL_OPEN] = self.s["detail_panel_open"]

    def bind_grid(self, grid: ui.aggrid) -> None:
        self.grid = grid

    def bind_refs(self, ctrl_refs: ControlsRefs) -> None:
        self.ctrl_refs = ctrl_refs

    def bind_detail(
        self,
        detail_outer: ui.column,
        detail_toggle_btn: ui.button,
        detail_body: ui.column,
    ) -> None:
        self.detail_outer = detail_outer
        self.detail_toggle_btn = detail_toggle_btn
        self.detail_body = detail_body

    def _passes_filters(self, row: dict) -> bool:
        return row_passes_filters(
            row,
            self.s["active_sources"],
            self.s["active_channels"],
            self.s["level_filter"],
        )

    def set_grid_data(self, rows: list[dict]) -> None:
        if not self.grid:
            return
        saved_ids = set(self.s["selected_ids"])
        self.s["row_data"] = rows
        self.grid.options["rowData"] = rows
        self.grid.update()
        apply_sort(self.grid, self.s["sort_order"])
        restore_selection(self.grid, saved_ids)
        if self.s["auto_scroll"]:
            scroll_to_edge(self.grid, len(self.s["row_data"]), self.s["sort_order"])

    def append_rows(self, rows: list[dict]) -> None:
        if not rows or not self.grid:
            return
        self.s["row_data"].extend(rows)
        self.grid.run_grid_method("applyTransaction", {"add": rows})
        if self.s["auto_scroll"]:
            scroll_to_edge(self.grid, len(self.s["row_data"]), self.s["sort_order"])

    def apply_sort(self) -> None:
        if self.grid:
            apply_sort(self.grid, self.s["sort_order"])

    async def reload(self) -> None:
        self.s["file_offsets"] = {}
        if self.s["search_text"]:
            self.s["is_search_mode"] = True
            await self._run_search(self.s["search_text"])
            return
        self.s["is_search_mode"] = False
        result = await run.io_bound(
            self._service.tail_initial,
            self._workspace,
        )
        if not result.ok or result.data is None:
            ui.notify(result.error or "Failed to load logs", color="negative")
            self.set_grid_data([])
            return
        self.s["file_offsets"] = result.data.file_offsets
        rows = [r for r in result.data.rows if self._passes_filters(r)]
        self.set_grid_data(rows)

    async def _run_search(self, query: str) -> None:
        result = await run.io_bound(self._service.search, self._workspace, query)
        if not result.ok:
            ui.notify(result.error or "Search failed", color="negative")
            self.set_grid_data([])
            return
        rows = [r for r in (result.data or []) if self._passes_filters(r)]
        self.set_grid_data(rows)

    async def poll(self) -> None:
        if self.s.get("paused") or self.s.get("is_search_mode"):
            return
        if not self.grid:
            return
        result = await run.io_bound(
            self._service.tail_after_offsets,
            self._workspace,
            dict(self.s["file_offsets"]),
        )
        if not result.ok or result.data is None:
            return
        self.s["file_offsets"] = result.data.file_offsets
        new_rows = [r for r in result.data.rows if self._passes_filters(r)]
        self.append_rows(new_rows)

    def on_source_click(self, name: str, btn: ui.button) -> None:
        active = self.s["active_sources"]
        if name not in active:
            active.append(name)
            set_chip_on(btn)
        else:
            self.s["active_sources"] = [s for s in active if s != name]
            set_chip_off(btn)
        self._persist_tab()
        channels_visible = "channels" in self.s["active_sources"]
        if self.ctrl_refs and self.ctrl_refs.channel_label:
            self.ctrl_refs.channel_label.set_visibility(channels_visible)
        if self.ctrl_refs and self.ctrl_refs.channel_select:
            self.ctrl_refs.channel_select.set_visibility(channels_visible)
        ui.timer(0.05, self.reload, once=True)

    def on_level_click(self, level: str, btn: ui.button) -> None:
        lf = self.s["level_filter"]
        if level in lf:
            self.s["level_filter"] = [x for x in lf if x != level]
            set_chip_off(btn)
        else:
            lf.append(level)
            set_chip_on(btn)
        self._tab()[_K_LEVELS] = list(self.s["level_filter"])
        ui.timer(0.05, self.reload, once=True)

    def on_channel_change(self, channels: list[str]) -> None:
        self.s["active_channels"] = channels
        self._tab()[_K_CHANNELS] = list(channels)
        ui.timer(0.05, self.reload, once=True)

    async def on_search(self, e) -> None:
        text = (e.value or "").strip() if hasattr(e, "value") else ""
        self.s["search_text"] = text
        self._tab()[_K_SEARCH] = text
        if text:
            self.s["is_search_mode"] = True
            await self._run_search(text)
        else:
            self.s["is_search_mode"] = False
            self.s["file_offsets"] = {}
            await self.reload()

    def toggle_sort(self) -> None:
        self.s["sort_order"] = "oldest" if self.s["sort_order"] == "newest" else "newest"
        self._tab()[_K_SORT] = self.s["sort_order"]
        if self.ctrl_refs:
            self.ctrl_refs.sort_btn.set_text(
                "Newest first" if self.s["sort_order"] == "newest" else "Oldest first"
            )
        if self.grid:
            apply_sort(self.grid, self.s["sort_order"])

    def toggle_pause(self) -> None:
        self.s["paused"] = not self.s["paused"]
        self._tab()[_K_PAUSED] = self.s["paused"]
        if not self.ctrl_refs or not self.poll_timer:
            return
        if self.s["paused"]:
            self.ctrl_refs.pause_btn.set_text("Resume")
            self.ctrl_refs.pause_btn.props("flat dense outlined icon=play_arrow")
        else:
            self.ctrl_refs.pause_btn.set_text("Pause")
            self.ctrl_refs.pause_btn.props("flat dense outlined icon=pause")
        self.poll_timer.active = not self.s["paused"]

    def toggle_auto_scroll(self) -> None:
        self.s["auto_scroll"] = not self.s["auto_scroll"]
        if not self.ctrl_refs:
            return
        if self.s["auto_scroll"]:
            self.ctrl_refs.auto_scroll_btn.set_text("Auto-scroll on")
            self.ctrl_refs.auto_scroll_btn.classes(remove="opacity-50")
            self.ctrl_refs.auto_scroll_btn.classes(add="text-positive")
        else:
            self.ctrl_refs.auto_scroll_btn.set_text("Auto-scroll off")
            self.ctrl_refs.auto_scroll_btn.classes(remove="text-positive")
            self.ctrl_refs.auto_scroll_btn.classes(add="opacity-50")

    def set_detail_panel_open(self, open_: bool) -> None:
        self.s["detail_panel_open"] = open_
        self._tab()[_K_DETAIL_OPEN] = open_
        if not self.detail_outer or not self.detail_toggle_btn or not self.detail_body:
            return
        if open_:
            self.detail_outer.classes(remove="hidden")
            set_chip_on(self.detail_toggle_btn)
            fill_detail_panel(self.detail_body, self.s.get("detail_row"), self._service)
        else:
            self.detail_outer.classes(add="hidden")
            set_chip_off(self.detail_toggle_btn)

    def on_cell_clicked(self, e) -> None:
        payload = getattr(e, "args", None)
        row = None
        if isinstance(payload, dict):
            row = payload.get("data")
        elif isinstance(payload, (list, tuple)) and payload:
            first = payload[0]
            if isinstance(first, dict):
                row = first.get("data")
        if not isinstance(row, dict):
            return
        self.s["detail_row"] = row
        if self.s["detail_panel_open"] and self.detail_body:
            fill_detail_panel(self.detail_body, row, self._service)

    async def on_selection_changed(self, _e) -> None:
        if not self.grid:
            return
        selected = await self.grid.get_selected_rows()
        self.s["selected_ids"] = {r["id"] for r in selected} if selected else set()

    async def mount(self) -> None:
        from hirocli.admin.features.logs.styles import LOG_COLORS_CSS

        ui.add_head_html(LOG_COLORS_CSS)

        page_row = ui.row().classes(
            "logs-main-row w-full items-stretch flex-nowrap gap-0"
        )
        with ui.column().classes(
            "logs-content-col flex-1 min-w-0 gap-3 p-6"
        ) as content_col:
            ctx = get_runtime_context()
            if ctx is None or ctx.log_dir is None:
                ui.label("Logs").classes("text-2xl font-semibold")
                error_banner(
                    message="Log directory is not available for this server context.",
                )
                content_col.move(page_row)
                return

            log_dir = ctx.log_dir
            gw_log_dir = ctx.gateway_log_dir
            if gw_log_dir is None:
                gw_log_dir = self._service.resolve_gateway_log_dir_fallback()

            loading_holder = ui.column()
            with loading_holder:
                loading_state(message="Loading logs…")

            layout_res = await run.io_bound(
                self._service.layout_info,
                log_dir,
                gw_log_dir,
            )
            if not layout_res.ok or layout_res.data is None:
                loading_holder.clear()
                with loading_holder:
                    ui.label("Logs").classes("text-2xl font-semibold")
                    error_banner(
                        message=layout_res.error or "Failed to inspect log directory.",
                    )
                content_col.move(page_row)
                return

            info = layout_res.data
            available_channels = info.available_channels
            has_gateway = info.has_gateway
            has_cli = info.has_cli

            # NiceGUI: first HTTP response runs before the WebSocket exists; storage.tab needs it.
            await context.client.connected()

            tab = self._tab()
            _default_sources = (
                ["server", "channels"]
                + (["gateway"] if has_gateway else [])
                + (["cli"] if has_cli else [])
            )
            _default_channels = available_channels[:]

            self.s = {
                "file_offsets": {},
                "row_data": [],
                "is_search_mode": False,
                "paused": bool(tab.get(_K_PAUSED, False)),
                "sort_order": tab.get(_K_SORT, "newest"),
                "active_sources": list(tab.get(_K_SOURCES, _default_sources)),
                "active_channels": list(tab.get(_K_CHANNELS, _default_channels)),
                "level_filter": list(tab.get(_K_LEVELS, LEVELS[:])),
                "search_text": str(tab.get(_K_SEARCH, "") or ""),
                "auto_scroll": True,
                "selected_ids": set(),
                "detail_row": None,
                "detail_panel_open": bool(tab.get(_K_DETAIL_OPEN, False)),
            }

            ctrl = self

            initial_rows: list[dict] = []
            tail_res = await run.io_bound(
                self._service.tail_initial,
                self._workspace,
            )
            if tail_res.ok and tail_res.data is not None:
                ctrl.s["file_offsets"] = tail_res.data.file_offsets
                initial_rows = [
                    r
                    for r in tail_res.data.rows
                    if row_passes_filters(
                        r,
                        ctrl.s["active_sources"],
                        ctrl.s["active_channels"],
                        ctrl.s["level_filter"],
                    )
                ]
                ctrl.s["row_data"] = initial_rows[:]
            elif not tail_res.ok:
                ui.notify(tail_res.error or "Failed to load initial logs", color="warning")

            loading_holder.delete()

            with ui.row().classes("w-full items-center justify-between gap-2 flex-wrap"):
                ui.label("Logs").classes("text-2xl font-semibold")
                detail_toggle_btn = ui.button(
                    "Log details",
                    icon="view_sidebar",
                ).props("dense outline rounded")
                if ctrl.s["detail_panel_open"]:
                    set_chip_on(detail_toggle_btn)
                else:
                    set_chip_off(detail_toggle_btn)

            build_source_filter_row(
                ctrl.s["active_sources"],
                has_gateway,
                has_cli,
                on_source_click=ctrl.on_source_click,
            )
            build_level_filter_row(
                ctrl.s["level_filter"],
                on_level_click=ctrl.on_level_click,
            )
            ctrl_refs = build_controls_row(
                search_text=ctrl.s["search_text"],
                sort_order=ctrl.s["sort_order"],
                paused=ctrl.s["paused"],
                auto_scroll=ctrl.s["auto_scroll"],
                available_channels=available_channels,
                active_channels=ctrl.s["active_channels"],
                channels_visible="channels" in ctrl.s["active_sources"],
                on_channel_change=ctrl.on_channel_change,
            )
            ctrl.bind_refs(ctrl_refs)

            grid_opts: dict = {
                "columnDefs": COL_DEFS,
                "rowData": initial_rows,
                "defaultColDef": {"resizable": True, "sortable": True, "filter": True},
                "rowSelection": "multiple",
                "animateRows": False,
                "rowHeight": 24,
                "headerHeight": 28,
                "suppressHorizontalScroll": False,
                "autoSizeStrategy": None,
                "rowClassRules": {"log-startup-row": "data.is_startup"},
                "tooltipShowDelay": 300,
                "tooltipInteraction": True,
            }
            grid = ui.aggrid(
                grid_opts,
                html_columns=[4, 5, 6, 7],
            ).classes("logs-grid-host w-full min-h-0 flex-1")
            ctrl.bind_grid(grid)

            _detail_base = "log-detail-panel w-[min(100%,420px)] shrink-0 flex flex-col"
            _detail_classes = (
                _detail_base
                if ctrl.s["detail_panel_open"]
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

            content_col.move(page_row)
            detail_outer.move(page_row)

            ctrl.bind_detail(detail_outer, detail_toggle_btn, detail_body)
            detail_toggle_btn.on_click(
                lambda: ctrl.set_detail_panel_open(not ctrl.s["detail_panel_open"])
            )
            close_detail_btn.on_click(lambda: ctrl.set_detail_panel_open(False))

            if ctrl.s["detail_panel_open"]:
                fill_detail_panel(detail_body, ctrl.s.get("detail_row"), self._service)

            grid.on("selectionChanged", ctrl.on_selection_changed)
            grid.on("cellClicked", ctrl.on_cell_clicked)

            ctrl_refs.search_input.on_value_change(ctrl.on_search)
            ctrl_refs.sort_btn.on_click(ctrl.toggle_sort)
            ctrl_refs.auto_scroll_btn.on_click(ctrl.toggle_auto_scroll)

            poll_timer = ui.timer(_POLL_INTERVAL, ctrl.poll)
            poll_timer.active = not ctrl.s["paused"]
            ctrl.poll_timer = poll_timer
            ctrl_refs.pause_btn.on_click(ctrl.toggle_pause)

            ui.timer(0.1, ctrl.apply_sort, once=True)
