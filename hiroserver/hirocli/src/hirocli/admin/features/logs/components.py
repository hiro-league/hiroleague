"""Logs filter bars and detail panel (composition only; handlers from controller)."""

from __future__ import annotations

import html
from collections.abc import Callable
from typing import TYPE_CHECKING, NamedTuple

from nicegui import ui

from hirocli.admin.features.logs.grid import LEVEL_CHIP_COLORS, LEVELS, set_chip_off, set_chip_on

if TYPE_CHECKING:
    from hirocli.admin.features.logs.service import LogsService


class SourceFilterRefs(NamedTuple):
    buttons: dict[str, ui.button]


class ControlsRefs(NamedTuple):
    search_input: ui.input
    sort_btn: ui.button
    pause_btn: ui.button
    auto_scroll_btn: ui.button
    channel_label: ui.label | None
    channel_select: ui.select | None


def _append_source_chip(
    name: str,
    label: str,
    active_sources: list[str],
    btns: dict[str, ui.button],
    on_source_click: Callable[[str, ui.button], None],
) -> None:
    is_on = name in active_sources
    btn = ui.button(label).props("dense rounded").classes("text-xs")
    if not is_on:
        set_chip_off(btn)
    btns[name] = btn
    btn.on_click(lambda n=name, b=btn: on_source_click(n, b))


def build_source_filter_row(
    active_sources: list[str],
    has_gateway: bool,
    has_cli: bool,
    *,
    on_source_click: Callable[[str, ui.button], None],
) -> SourceFilterRefs:
    btns: dict[str, ui.button] = {}

    with ui.row().classes("items-center gap-2 flex-wrap"):
        ui.label("Source:").classes("text-sm font-medium opacity-60 self-center")

        _append_source_chip("server", "Server", active_sources, btns, on_source_click)
        _append_source_chip("channels", "Channels", active_sources, btns, on_source_click)
        if has_gateway:
            _append_source_chip("gateway", "Gateway", active_sources, btns, on_source_click)
        if has_cli:
            _append_source_chip("cli", "CLI", active_sources, btns, on_source_click)

    return SourceFilterRefs(buttons=btns)


def build_level_filter_row(
    level_filter: list[str],
    *,
    on_level_click: Callable[[str, ui.button], None],
) -> dict[str, ui.button]:
    btns: dict[str, ui.button] = {}

    with ui.row().classes("items-center gap-2 flex-wrap"):
        ui.label("Level:").classes("text-sm font-medium opacity-60 self-center")

        for lvl in LEVELS:
            is_on = lvl in level_filter
            color = LEVEL_CHIP_COLORS.get(lvl, "grey")
            btn = ui.button(lvl).props(f"dense rounded color={color}").classes("text-xs")
            if not is_on:
                set_chip_off(btn)
            btns[lvl] = btn
            btn.on_click(lambda l=lvl, b=btn: on_level_click(l, b))

    return btns


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

            channel_select.on_value_change(
                lambda e, cb=on_channel_change: cb(list(e.value or []))
            )

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


def _detail_render_field(
    service: LogsService,
    title: str,
    text: str,
    *,
    try_structure: bool = False,
) -> None:
    ui.label(title).classes("log-detail-field-label")
    raw = text or ""
    if try_structure:
        ok, out = service.pretty_print_log_field(raw)
        if ok:
            ui.html(f'<pre class="log-detail-json">{html.escape(out)}</pre>')
            return
    ui.label(raw if raw else "—").classes(
        "text-sm whitespace-pre-wrap break-words mt-0.5"
    )


def _detail_render_extra_body(service: LogsService, raw_extra: str) -> None:
    ui.label("Extra").classes("log-detail-field-label")
    segs = service.split_log_extra_segments(raw_extra)
    if not segs:
        ui.label("—").classes("text-sm opacity-50 mt-0.5")
        return
    for seg in segs:
        k, v = service.log_segment_key_value(seg)
        sub = k if k else "value"
        ui.label(sub).classes("log-detail-field-label")
        ok, out = service.pretty_print_log_field(v)
        if ok:
            ui.html(f'<pre class="log-detail-json">{html.escape(out)}</pre>')
        else:
            ui.label(v if v else "—").classes(
                "text-sm whitespace-pre-wrap break-words mt-0.5"
            )


def fill_detail_panel(
    detail_body: ui.column,
    row: dict | None,
    service: LogsService,
) -> None:
    """Rebuild *detail_body* from a grid row dict."""
    detail_body.clear()
    with detail_body:
        if not row:
            ui.label("Click a row in the table to inspect a log line.").classes(
                "text-sm opacity-50"
            )
            return

        ts = row.get("timestamp")
        ts_line = (
            f"{row.get('date_display', '')} {row.get('timestamp_display', '')}".strip()
        )
        _detail_render_field(service, "Time", ts_line)
        _detail_render_field(service, "Timestamp (epoch)", str(ts) if ts is not None else "")
        _detail_render_field(service, "Source", str(row.get("source", "") or ""))
        _detail_render_field(service, "Level", str(row.get("level", "") or ""))
        _detail_render_field(service, "Module", str(row.get("module", "") or ""))
        _detail_render_field(
            service,
            "Message",
            str(row.get("message", "") or ""),
            try_structure=True,
        )

        raw_extra = str(row.get("extra", "") or "")
        _detail_render_extra_body(service, raw_extra)
