"""Metrics page widgets — ECharts cards and tables (colors from shared/theme.py)."""

from __future__ import annotations

from dataclasses import dataclass

from nicegui import ui

from hirocli.admin.shared.theme import METRICS_ECHART_COLORS


def make_area_chart(color_key: str, *, y_max: int | None = None, fmt: str = "{value}%") -> ui.echart:
    color = METRICS_ECHART_COLORS[color_key]
    y_axis: dict = {"type": "value", "min": 0, "axisLabel": {"formatter": fmt}}
    if y_max is not None:
        y_axis["max"] = y_max
    return ui.echart(
        {
            "animation": False,
            "grid": {"top": 10, "bottom": 20, "left": 50, "right": 10},
            "xAxis": {"type": "time", "show": False},
            "yAxis": y_axis,
            "series": [
                {
                    "type": "line",
                    "data": [],
                    "smooth": True,
                    "symbol": "none",
                    "lineStyle": {"color": color, "width": 2},
                    "areaStyle": {"color": color, "opacity": 0.15},
                }
            ],
            "tooltip": {"trigger": "axis"},
        }
    ).classes("w-full h-40")


def make_dual_area_chart(color_key_a: str, color_key_b: str, *, fmt: str = "{value}") -> ui.echart:
    color_a = METRICS_ECHART_COLORS[color_key_a]
    color_b = METRICS_ECHART_COLORS[color_key_b]
    return ui.echart(
        {
            "animation": False,
            "grid": {"top": 10, "bottom": 20, "left": 50, "right": 10},
            "xAxis": {"type": "time", "show": False},
            "yAxis": {"type": "value", "min": 0, "axisLabel": {"formatter": fmt}},
            "legend": {"show": False},
            "series": [
                {
                    "name": "out",
                    "type": "line",
                    "data": [],
                    "smooth": True,
                    "symbol": "none",
                    "lineStyle": {"color": color_a, "width": 2},
                    "areaStyle": {"color": color_a, "opacity": 0.15},
                },
                {
                    "name": "in",
                    "type": "line",
                    "data": [],
                    "smooth": True,
                    "symbol": "none",
                    "lineStyle": {"color": color_b, "width": 2},
                    "areaStyle": {"color": color_b, "opacity": 0.15},
                },
            ],
            "tooltip": {"trigger": "axis"},
        }
    ).classes("w-full h-40")


@dataclass
class MetricsControlRefs:
    enable_switch: ui.switch
    interval_slider: ui.slider
    interval_label: ui.label
    status_label: ui.label


@dataclass
class MetricsProcessRefs:
    proc_cpu_label: ui.label
    proc_pid_label: ui.label
    proc_cpu_chart: ui.echart
    proc_rss_label: ui.label
    proc_vms_label: ui.label
    proc_rss_chart: ui.echart
    proc_threads_label: ui.label
    proc_threads_chart: ui.echart


@dataclass
class MetricsDiskNetRefs:
    children_table: ui.table
    children_total_label: ui.label
    disk_label: ui.label
    disk_detail_label: ui.label
    disk_rate_label: ui.label
    disk_chart: ui.echart
    net_label: ui.label
    net_detail_label: ui.label
    net_pkt_label: ui.label
    net_chart: ui.echart


@dataclass
class MetricsSystemRefs:
    sys_cpu_label: ui.label
    sys_cpu_cores_label: ui.label
    sys_cpu_chart: ui.echart
    sys_mem_label: ui.label
    sys_mem_detail_label: ui.label
    sys_mem_chart: ui.echart


def build_controls_card() -> MetricsControlRefs:
    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-6 p-1"):
            enable_switch = ui.switch("Enable metrics", value=True)
            interval_slider = ui.slider(min=1.0, max=10.0, step=0.5, value=2.0).props(
                "label-always"
            ).classes("w-48")
            interval_label = ui.label("Interval: 2.0s").classes("text-sm opacity-60")
            status_label = ui.label("").classes("text-sm opacity-60")
    return MetricsControlRefs(
        enable_switch=enable_switch,
        interval_slider=interval_slider,
        interval_label=interval_label,
        status_label=status_label,
    )


def build_process_section() -> MetricsProcessRefs:
    ui.label("Server Process").classes("text-lg font-semibold opacity-80")
    with ui.grid(columns=3).classes("w-full gap-4"):
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-3 p-1"):
                ui.icon("speed").classes("text-3xl opacity-50")
                ui.label("Process CPU").classes("text-lg font-semibold")
            proc_cpu_label = ui.label("—").classes("text-4xl font-bold px-1")
            proc_pid_label = ui.label("").classes("text-sm opacity-60 px-1")
            proc_cpu_chart = make_area_chart("proc_cpu", y_max=100)

        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-3 p-1"):
                ui.icon("memory").classes("text-3xl opacity-50")
                ui.label("Process Memory (RSS)").classes("text-lg font-semibold")
            proc_rss_label = ui.label("—").classes("text-4xl font-bold px-1")
            proc_vms_label = ui.label("").classes("text-sm opacity-60 px-1")
            proc_rss_chart = make_area_chart("proc_rss", y_max=None, fmt="{value} MB")

        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-3 p-1"):
                ui.icon("hub").classes("text-3xl opacity-50")
                ui.label("Threads").classes("text-lg font-semibold")
            proc_threads_label = ui.label("—").classes("text-4xl font-bold px-1")
            ui.label("").classes("text-sm opacity-60 px-1")
            proc_threads_chart = make_area_chart("proc_threads", y_max=None, fmt="{value}")

    return MetricsProcessRefs(
        proc_cpu_label=proc_cpu_label,
        proc_pid_label=proc_pid_label,
        proc_cpu_chart=proc_cpu_chart,
        proc_rss_label=proc_rss_label,
        proc_vms_label=proc_vms_label,
        proc_rss_chart=proc_rss_chart,
        proc_threads_label=proc_threads_label,
        proc_threads_chart=proc_threads_chart,
    )


def build_plugins_and_disk_net_section() -> MetricsDiskNetRefs:
    ui.label("Channel Plugins").classes("text-lg font-semibold opacity-80")
    children_columns = [
        {"name": "name", "label": "Channel", "field": "name", "align": "left"},
        {"name": "pid", "label": "PID", "field": "pid", "align": "center"},
        {"name": "alive", "label": "Status", "field": "alive", "align": "center"},
        {"name": "cpu", "label": "CPU %", "field": "cpu", "align": "right"},
        {"name": "rss", "label": "RSS", "field": "rss", "align": "right"},
        {"name": "threads", "label": "Threads", "field": "threads", "align": "right"},
    ]
    children_table = ui.table(columns=children_columns, rows=[], row_key="name").classes("w-full")
    children_total_label = ui.label("").classes("text-sm opacity-60")

    ui.label("Disk & Network").classes("text-lg font-semibold opacity-80")
    with ui.grid(columns=2).classes("w-full gap-4"):
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-3 p-1"):
                ui.icon("storage").classes("text-3xl opacity-50")
                ui.label("Disk Usage").classes("text-lg font-semibold")
            disk_label = ui.label("—").classes("text-4xl font-bold px-1")
            disk_detail_label = ui.label("").classes("text-sm opacity-60 px-1")
            disk_rate_label = ui.label("").classes("text-sm opacity-60 px-1")
            disk_chart = make_dual_area_chart("disk_write", "disk_read", fmt="{value} KB/s")

        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-3 p-1"):
                ui.icon("wifi").classes("text-3xl opacity-50")
                ui.label("Network I/O").classes("text-lg font-semibold")
            net_label = ui.label("—").classes("text-4xl font-bold px-1")
            net_detail_label = ui.label("").classes("text-sm opacity-60 px-1")
            net_pkt_label = ui.label("").classes("text-sm opacity-60 px-1")
            net_chart = make_dual_area_chart("net_sent", "net_recv", fmt="{value} KB/s")

    return MetricsDiskNetRefs(
        children_table=children_table,
        children_total_label=children_total_label,
        disk_label=disk_label,
        disk_detail_label=disk_detail_label,
        disk_rate_label=disk_rate_label,
        disk_chart=disk_chart,
        net_label=net_label,
        net_detail_label=net_detail_label,
        net_pkt_label=net_pkt_label,
        net_chart=net_chart,
    )


def build_system_expansion() -> MetricsSystemRefs:
    with ui.expansion("System-wide", icon="monitor_heart").classes("w-full"):
        with ui.grid(columns=2).classes("w-full gap-4"):
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center gap-3 p-1"):
                    ui.icon("developer_board").classes("text-3xl opacity-50")
                    ui.label("System CPU").classes("text-lg font-semibold")
                sys_cpu_label = ui.label("—").classes("text-4xl font-bold px-1")
                sys_cpu_cores_label = ui.label("").classes("text-sm opacity-60 px-1")
                sys_cpu_chart = make_area_chart("sys_cpu", y_max=100)

            with ui.card().classes("w-full"):
                with ui.row().classes("items-center gap-3 p-1"):
                    ui.icon("sd_card").classes("text-3xl opacity-50")
                    ui.label("System Memory").classes("text-lg font-semibold")
                sys_mem_label = ui.label("—").classes("text-4xl font-bold px-1")
                sys_mem_detail_label = ui.label("").classes("text-sm opacity-60 px-1")
                sys_mem_chart = make_area_chart("sys_mem", y_max=100)

    return MetricsSystemRefs(
        sys_cpu_label=sys_cpu_label,
        sys_cpu_cores_label=sys_cpu_cores_label,
        sys_cpu_chart=sys_cpu_chart,
        sys_mem_label=sys_mem_label,
        sys_mem_detail_label=sys_mem_detail_label,
        sys_mem_chart=sys_mem_chart,
    )
