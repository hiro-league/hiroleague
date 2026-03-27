"""Metrics page — collector from HTTP app state, timer-driven charts (guidelines §2.3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hiro_commons.log import Logger
from nicegui import ui

from hirocli.admin.features.metrics.components import (
    MetricsControlRefs,
    MetricsDiskNetRefs,
    MetricsProcessRefs,
    MetricsSystemRefs,
    build_controls_card,
    build_plugins_and_disk_net_section,
    build_process_section,
    build_system_expansion,
)
from hirocli.admin.features.metrics.service import MetricsAdminService
from hirocli.admin.shared.formatters import trim_series_in_place
from hirocli.admin.shared.ui.empty_state import empty_state

if TYPE_CHECKING:
    from hirocli.services.metrics import MetricsCollector

_MAX_CHART_POINTS = 60
_TIMER_INTERVAL = 2.0

_log = Logger.get("ADMIN.METRICS")


class MetricsPageController:
    """Wires MetricsCollector to ECharts + tables; service owns formatting logic."""

    def __init__(self) -> None:
        self._service = MetricsAdminService()
        self._collector: MetricsCollector | None = None
        self._ctrl: MetricsControlRefs | None = None
        self._proc: MetricsProcessRefs | None = None
        self._disk_net: MetricsDiskNetRefs | None = None
        self._sys: MetricsSystemRefs | None = None
        self._proc_cpu_data: list[list] = []
        self._proc_rss_data: list[list] = []
        self._proc_threads_data: list[list] = []
        self._disk_read_data: list[list] = []
        self._disk_write_data: list[list] = []
        self._net_sent_data: list[list] = []
        self._net_recv_data: list[list] = []
        self._sys_cpu_data: list[list] = []
        self._sys_mem_data: list[list] = []
        # Avoid toast spam if the timer keeps failing; reset after a successful tick.
        self._tick_user_notified_error: bool = False

    def _resolve_collector(self) -> MetricsCollector | None:
        from hirocli.runtime.http_server import app as http_app

        return getattr(http_app.state, "metrics_collector", None)

    def _on_control_changed(self, _event: object = None) -> None:
        """Switch/slider → collector.configure (avoids inline lambdas per guidelines)."""
        self._apply_config_from_ui()

    def _apply_config_from_ui(self) -> None:
        if self._collector is None or self._ctrl is None:
            return
        result = self._service.configure(
            self._collector,
            enabled=self._ctrl.enable_switch.value,
            interval=self._ctrl.interval_slider.value,
        )
        if not result.ok:
            ui.notify(result.error or "Failed to update metrics config", type="negative")
            return
        assert result.data is not None
        self._ctrl.interval_label.text = f"Interval: {result.data.interval:.1f}s"

    def _on_timer_tick(self) -> None:
        if self._collector is None or self._ctrl is None:
            return
        try:
            payload = self._service.prepare_tick(self._collector)
            self._ctrl.status_label.text = payload.status_text
            if payload.frame is None:
                self._tick_user_notified_error = False
                return
            f = payload.frame
            c = f.chart
            proc = self._proc
            dn = self._disk_net
            sysr = self._sys
            if proc is None or dn is None or sysr is None:
                return

            proc.proc_cpu_label.text = f.process_cpu_label
            proc.proc_pid_label.text = f.process_pid_caption
            proc.proc_rss_label.text = f.process_rss_label
            proc.proc_vms_label.text = f.process_vms_caption
            proc.proc_threads_label.text = f.process_threads_label

            self._proc_cpu_data.append([c.ts_ms, c.proc_cpu])
            trim_series_in_place(self._proc_cpu_data, _MAX_CHART_POINTS)
            proc.proc_cpu_chart.options["series"][0]["data"] = self._proc_cpu_data
            proc.proc_cpu_chart.update()

            self._proc_rss_data.append([c.ts_ms, c.proc_rss_mb])
            trim_series_in_place(self._proc_rss_data, _MAX_CHART_POINTS)
            proc.proc_rss_chart.options["series"][0]["data"] = self._proc_rss_data
            proc.proc_rss_chart.update()

            self._proc_threads_data.append([c.ts_ms, c.proc_threads])
            trim_series_in_place(self._proc_threads_data, _MAX_CHART_POINTS)
            proc.proc_threads_chart.options["series"][0]["data"] = self._proc_threads_data
            proc.proc_threads_chart.update()

            dn.children_table.rows = f.children_rows
            dn.children_table.update()
            dn.children_total_label.text = f.children_total_caption

            dn.disk_label.text = f.disk_percent_label
            dn.disk_detail_label.text = f.disk_detail_caption
            dn.disk_rate_label.text = f.disk_rate_caption
            self._disk_read_data.append([c.ts_ms, c.disk_read_kb])
            self._disk_write_data.append([c.ts_ms, c.disk_write_kb])
            trim_series_in_place(self._disk_read_data, _MAX_CHART_POINTS)
            trim_series_in_place(self._disk_write_data, _MAX_CHART_POINTS)
            dn.disk_chart.options["series"][0]["data"] = self._disk_write_data
            dn.disk_chart.options["series"][1]["data"] = self._disk_read_data
            dn.disk_chart.update()

            dn.net_label.text = f.net_total_rate_label
            dn.net_detail_label.text = f.net_detail_caption
            dn.net_pkt_label.text = f.net_packets_caption
            self._net_sent_data.append([c.ts_ms, c.net_sent_kb])
            self._net_recv_data.append([c.ts_ms, c.net_recv_kb])
            trim_series_in_place(self._net_sent_data, _MAX_CHART_POINTS)
            trim_series_in_place(self._net_recv_data, _MAX_CHART_POINTS)
            dn.net_chart.options["series"][0]["data"] = self._net_sent_data
            dn.net_chart.options["series"][1]["data"] = self._net_recv_data
            dn.net_chart.update()

            sysr.sys_cpu_label.text = f.sys_cpu_label
            sysr.sys_cpu_cores_label.text = f.sys_cpu_cores_caption
            self._sys_cpu_data.append([c.ts_ms, c.sys_cpu])
            trim_series_in_place(self._sys_cpu_data, _MAX_CHART_POINTS)
            sysr.sys_cpu_chart.options["series"][0]["data"] = self._sys_cpu_data
            sysr.sys_cpu_chart.update()

            sysr.sys_mem_label.text = f.sys_mem_label
            sysr.sys_mem_detail_label.text = f.sys_mem_detail_caption
            self._sys_mem_data.append([c.ts_ms, c.sys_mem_pct])
            trim_series_in_place(self._sys_mem_data, _MAX_CHART_POINTS)
            sysr.sys_mem_chart.options["series"][0]["data"] = self._sys_mem_data
            sysr.sys_mem_chart.update()

            self._tick_user_notified_error = False
        except Exception as exc:
            # Timer callbacks must not die silently — charts would freeze with no user feedback.
            _log.error(
                "❌ Metrics UI refresh failed — HiroAdmin · chart/table update",
                error=str(exc),
                exc_info=True,
            )
            self._ctrl.status_label.text = "Update failed — check server logs"
            if not self._tick_user_notified_error:
                self._tick_user_notified_error = True
                ui.notify(
                    "Metrics refresh failed; updates paused until the next successful tick.",
                    type="negative",
                )

    async def mount(self) -> None:
        self._collector = self._resolve_collector()

        with ui.column().classes("w-full gap-6 p-6"):
            ui.label("Server Metrics").classes("text-2xl font-semibold")

            if self._collector is None:
                empty_state(
                    message="Metrics collector is not available.",
                    icon="monitoring",
                )
                return

            self._ctrl = build_controls_card()
            self._ctrl.enable_switch.value = self._collector.enabled
            self._ctrl.interval_slider.value = self._collector.interval
            self._ctrl.interval_label.text = f"Interval: {self._collector.interval:.1f}s"

            self._ctrl.enable_switch.on_value_change(self._on_control_changed)
            self._ctrl.interval_slider.on_value_change(self._on_control_changed)

            self._proc = build_process_section()
            self._disk_net = build_plugins_and_disk_net_section()
            self._sys = build_system_expansion()

        ui.timer(_TIMER_INTERVAL, self._on_timer_tick)
