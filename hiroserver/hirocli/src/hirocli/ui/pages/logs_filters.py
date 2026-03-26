"""Filter-bar UI builders for the admin Logs page.

Each builder creates a NiceGUI row of controls and returns a NamedTuple of
element references that the page needs for cross-component wiring.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from nicegui import ui

from hirocli.ui.pages.logs_grid import (
    LEVEL_CHIP_COLORS,
    LEVELS,
    set_chip_off,
    set_chip_on,
)


# ---------------------------------------------------------------------------
# Return types — lightweight containers for element refs the page needs.
# ---------------------------------------------------------------------------
class SourceFilterRefs(NamedTuple):
    buttons: dict[str, ui.button]


class ControlsRefs(NamedTuple):
    search_input: ui.input
    sort_btn: ui.button
    pause_btn: ui.button
    auto_scroll_btn: ui.button
    channel_label: ui.label | None
    channel_select: ui.select | None


# ---------------------------------------------------------------------------
# Source filter row
# ---------------------------------------------------------------------------
def build_source_filter_row(
    active_sources: list[str],
    has_gateway: bool,
    has_cli: bool,
    *,
    on_toggle: Callable[[str, bool], None],
) -> SourceFilterRefs:
    """Render Source chip-buttons and return element refs.

    *on_toggle(source_name, is_now_active)* is called after the chip state
    changes so the page can persist prefs and reload data.
    """
    btns: dict[str, ui.button] = {}

    with ui.row().classes("items-center gap-2 flex-wrap"):
        ui.label("Source:").classes("text-sm font-medium opacity-60 self-center")

        def _make(name: str, label: str) -> None:
            is_on = name in active_sources
            btn = ui.button(label).props("dense rounded").classes("text-xs")
            if not is_on:
                set_chip_off(btn)
            btns[name] = btn

            def _on_click(n=name, b=btn) -> None:
                now_active = n not in active_sources
                if now_active:
                    active_sources.append(n)
                    set_chip_on(b)
                else:
                    active_sources[:] = [s for s in active_sources if s != n]
                    set_chip_off(b)
                on_toggle(n, now_active)

            btn.on_click(_on_click)

        _make("server", "Server")
        _make("channels", "Channels")
        if has_gateway:
            _make("gateway", "Gateway")
        if has_cli:
            _make("cli", "CLI")

    return SourceFilterRefs(buttons=btns)


# ---------------------------------------------------------------------------
# Level filter row
# ---------------------------------------------------------------------------
def build_level_filter_row(
    level_filter: list[str],
    *,
    on_change: Callable[[list[str]], None],
) -> dict[str, ui.button]:
    """Render Level chip-buttons and return the button map.

    *on_change(current_levels)* fires after every toggle so the page can
    persist prefs and reload data.
    """
    btns: dict[str, ui.button] = {}

    with ui.row().classes("items-center gap-2 flex-wrap"):
        ui.label("Level:").classes("text-sm font-medium opacity-60 self-center")

        def _make(lvl: str) -> None:
            is_on = lvl in level_filter
            color = LEVEL_CHIP_COLORS.get(lvl, "grey")
            btn = ui.button(lvl).props(f"dense rounded color={color}").classes("text-xs")
            if not is_on:
                set_chip_off(btn)
            btns[lvl] = btn

            def _on_click(l=lvl, b=btn) -> None:
                if l in level_filter:
                    level_filter[:] = [x for x in level_filter if x != l]
                    set_chip_off(b)
                else:
                    level_filter.append(l)
                    set_chip_on(b)
                on_change(level_filter)

            btn.on_click(_on_click)

        for lvl in LEVELS:
            _make(lvl)

    return btns


# ---------------------------------------------------------------------------
# Controls row: search | sort | pause | auto-scroll | channel filter
# ---------------------------------------------------------------------------
def build_controls_row(
    search_text: str,
    sort_order: str,
    paused: bool,
    auto_scroll: bool,
    available_channels: list[str],
    active_channels: list[str],
    channels_visible: bool,
    *,
    on_channel_change: Callable[[list[str]], None],
) -> ControlsRefs:
    """Render the controls row and return element refs.

    Event handlers for search/sort/pause/auto-scroll are wired by the page
    after receiving the refs (they couple to grid helpers / timers).
    Channel-change is self-contained so it uses *on_channel_change* directly.
    """
    channel_label: ui.label | None = None
    channel_select: ui.select | None = None

    with ui.row().classes("items-center gap-3 flex-wrap"):
        search_input = (
            ui.input(placeholder="Search logs…", value=search_text)
            .classes("min-w-64")
            .props("dense outlined clearable")
        )

        sort_btn = ui.button(
            "Newest first" if sort_order == "newest" else "Oldest first",
            icon="swap_vert",
        ).props("flat dense outlined")

        pause_btn = ui.button(
            "Resume" if paused else "Pause",
            icon="play_arrow" if paused else "pause",
        ).props("flat dense outlined")

        auto_scroll_btn = ui.button(
            "Auto-scroll on",
            icon="vertical_align_bottom",
        ).props("flat dense outlined")
        auto_scroll_btn.classes("text-positive" if auto_scroll else "opacity-50")

        if available_channels:
            channel_label = ui.label("Channel:").classes("text-sm opacity-50 self-center")
            channel_select = (
                ui.select(
                    available_channels,
                    multiple=True,
                    value=active_channels or available_channels,
                    label="",
                )
                .classes("min-w-32 max-w-60")
                .props("dense outlined")
            )

            def _on_ch_change(e) -> None:
                on_channel_change(list(e.value or []))

            channel_select.on_value_change(_on_ch_change)

            channel_label.set_visibility(channels_visible)
            channel_select.set_visibility(channels_visible)

    return ControlsRefs(
        search_input=search_input,
        sort_btn=sort_btn,
        pause_btn=pause_btn,
        auto_scroll_btn=auto_scroll_btn,
        channel_label=channel_label,
        channel_select=channel_select,
    )
