"""Controller for the admin Logs page.

LogsPageController owns all mutable page state and handles:
- Data pipeline: loading, searching, incremental polling, grid updates
- UI event handlers: filter toggles, sort, pause, auto-scroll, search

Two-step initialisation is required because the filter-row widgets are built
before the grid and ctrl_refs exist in the page layout:

    ctrl = LogsPageController(initial_state=_s)
    # ... build filter rows passing ctrl methods as callbacks ...
    ctrl.bind_refs(ctrl_refs)   # after build_controls_row
    ctrl.bind_grid(grid)        # after ui.aggrid
"""

from __future__ import annotations

import json

from nicegui import app as nicegui_app, ui

from hirocli.ui.pages.logs_detail import fill_detail_panel
from hirocli.ui.pages.logs_filters import ControlsRefs
from hirocli.ui.pages.logs_grid import (
    apply_sort,
    restore_selection,
    row_passes_filters,
    scroll_to_edge,
    set_chip_off,
    set_chip_on,
)

_INITIAL_LINES = 500  # lines loaded on first open


class LogsPageController:
    """Owns page state and drives all runtime behaviour for the Logs page."""

    def __init__(self, initial_state: dict) -> None:
        self.s = initial_state
        self.grid: ui.aggrid | None = None
        self.ctrl_refs: ControlsRefs | None = None
        self.poll_timer: ui.timer | None = None
        self.detail_outer: ui.column | None = None
        self.detail_toggle_btn: ui.button | None = None
        self.detail_body: ui.column | None = None

    # ------------------------------------------------------------------
    # Two-step binding (called after layout elements are created)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _workspace(self) -> str | None:
        return nicegui_app.storage.user.get("selected_workspace")

    @property
    def _prefs(self):
        return nicegui_app.storage.user

    def _passes_filters(self, row: dict) -> bool:
        return row_passes_filters(
            row,
            self.s["active_sources"],
            self.s["active_channels"],
            self.s["level_filter"],
        )

    # ------------------------------------------------------------------
    # Grid update helpers
    # ------------------------------------------------------------------

    def set_grid_data(self, rows: list[dict]) -> None:
        # Snapshot selected IDs before grid.update() clears selection.
        saved_ids = set(self.s["selected_ids"])
        self.s["row_data"] = rows
        self.grid.options["rowData"] = rows
        self.grid.update()
        # grid.update() resets AG Grid column state — re-apply sort.
        apply_sort(self.grid, self.s["sort_order"])
        restore_selection(self.grid, saved_ids)
        if self.s["auto_scroll"]:
            scroll_to_edge(self.grid, len(self.s["row_data"]), self.s["sort_order"])

    def append_rows(self, rows: list[dict]) -> None:
        if not rows:
            return
        self.s["row_data"].extend(rows)
        # applyTransaction adds rows without replacing existing data,
        # so AG Grid column state, sort order, and selection are preserved.
        # Do NOT assign grid.options["rowData"] here — NiceGUI's reactive
        # sync would push a full rowData replace to the client, duplicating
        # the rows and resetting sort. set_grid_data handles the full sync.
        self.grid.run_grid_method("applyTransaction", {"add": rows})
        if self.s["auto_scroll"]:
            scroll_to_edge(self.grid, len(self.s["row_data"]), self.s["sort_order"])

    def apply_sort(self) -> None:
        apply_sort(self.grid, self.s["sort_order"])

    # ------------------------------------------------------------------
    # Data pipeline
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Reset offsets and reload from disk, or re-run search if active."""
        self.s["file_offsets"] = {}
        if self.s["search_text"]:
            self.s["is_search_mode"] = True
            self.search(self.s["search_text"])
            return
        self.s["is_search_mode"] = False
        try:
            from hirocli.tools.logs import LogTailTool
            result = LogTailTool().execute(
                source="all",
                lines=_INITIAL_LINES,
                workspace=self._workspace,
            )
            self.s["file_offsets"] = result.file_offsets
            rows = [r for r in result.rows if self._passes_filters(r)]
            self.set_grid_data(rows)
        except Exception:
            pass

    def search(self, query: str) -> None:
        """Run a full-text search and replace grid contents with results."""
        try:
            from hirocli.tools.logs import LogSearchTool
            result = LogSearchTool().execute(
                source="all",
                query=query,
                workspace=self._workspace,
            )
            rows = [r for r in result.rows if self._passes_filters(r)]
            self.set_grid_data(rows)
        except Exception:
            pass

    def poll(self) -> None:
        """Incremental tail poll — appends new rows since last offset."""
        if self.s["paused"] or self.s["is_search_mode"]:
            return
        try:
            from hirocli.tools.logs import LogTailTool
            offsets_json = (
                json.dumps(self.s["file_offsets"]) if self.s["file_offsets"] else None
            )
            result = LogTailTool().execute(
                source="all",
                after_offsets=offsets_json,
                workspace=self._workspace,
            )
            self.s["file_offsets"] = result.file_offsets
            new_rows = [r for r in result.rows if self._passes_filters(r)]
            self.append_rows(new_rows)
        except RuntimeError:
            pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Filter event handlers
    # ------------------------------------------------------------------

    def on_source_toggle(self, _name: str, _is_active: bool) -> None:
        self._prefs["logs_sources"] = self.s["active_sources"]
        channels_visible = "channels" in self.s["active_sources"]
        if self.ctrl_refs and self.ctrl_refs.channel_label:
            self.ctrl_refs.channel_label.set_visibility(channels_visible)
        if self.ctrl_refs and self.ctrl_refs.channel_select:
            self.ctrl_refs.channel_select.set_visibility(channels_visible)
        self.reload()

    def on_level_change(self, levels: list[str]) -> None:
        self._prefs["logs_level_filter"] = levels
        self.reload()

    def on_channel_change(self, channels: list[str]) -> None:
        self.s["active_channels"] = channels
        self._prefs["logs_channels"] = channels
        self.reload()

    # ------------------------------------------------------------------
    # Control bar event handlers
    # ------------------------------------------------------------------

    def on_search(self, e) -> None:
        text = (e.value or "").strip() if hasattr(e, "value") else ""
        self.s["search_text"] = text
        self._prefs["logs_search_text"] = text
        if text:
            self.s["is_search_mode"] = True
            self.search(text)
        else:
            self.s["is_search_mode"] = False
            self.s["file_offsets"] = {}
            self.reload()

    def toggle_sort(self) -> None:
        self.s["sort_order"] = "oldest" if self.s["sort_order"] == "newest" else "newest"
        self._prefs["logs_sort_order"] = self.s["sort_order"]
        self.ctrl_refs.sort_btn.set_text(
            "Newest first" if self.s["sort_order"] == "newest" else "Oldest first"
        )
        apply_sort(self.grid, self.s["sort_order"])

    def toggle_pause(self) -> None:
        self.s["paused"] = not self.s["paused"]
        self._prefs["logs_paused"] = self.s["paused"]
        if self.s["paused"]:
            self.ctrl_refs.pause_btn.set_text("Resume")
            self.ctrl_refs.pause_btn.props("flat dense outlined icon=play_arrow")
        else:
            self.ctrl_refs.pause_btn.set_text("Pause")
            self.ctrl_refs.pause_btn.props("flat dense outlined icon=pause")
        self.poll_timer.active = not self.s["paused"]

    def toggle_auto_scroll(self) -> None:
        self.s["auto_scroll"] = not self.s["auto_scroll"]
        if self.s["auto_scroll"]:
            self.ctrl_refs.auto_scroll_btn.set_text("Auto-scroll on")
            self.ctrl_refs.auto_scroll_btn.classes(remove="opacity-50")
            self.ctrl_refs.auto_scroll_btn.classes(add="text-positive")
        else:
            self.ctrl_refs.auto_scroll_btn.set_text("Auto-scroll off")
            self.ctrl_refs.auto_scroll_btn.classes(remove="text-positive")
            self.ctrl_refs.auto_scroll_btn.classes(add="opacity-50")

    # ------------------------------------------------------------------
    # Detail panel handlers
    # ------------------------------------------------------------------

    def set_detail_panel_open(self, open_: bool) -> None:
        self.s["detail_panel_open"] = open_
        self._prefs["logs_detail_panel_open"] = open_
        if open_:
            self.detail_outer.classes(remove="hidden")
            set_chip_on(self.detail_toggle_btn)
            fill_detail_panel(self.detail_body, self.s.get("detail_row"))
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
        if self.s["detail_panel_open"]:
            fill_detail_panel(self.detail_body, row)

    async def on_selection_changed(self, _e) -> None:
        selected = await self.grid.get_selected_rows()
        self.s["selected_ids"] = {r["id"] for r in selected} if selected else set()
