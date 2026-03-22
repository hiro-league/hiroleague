"""Metrics page — live server resource monitoring.

Sections (top → bottom):
  1. Controls — enable/disable, interval slider
  2. Server Process — CPU, RSS, threads for the main hirocli process
  3. Channel Plugins — per-plugin CPU, RSS, threads + totals row
  4. Disk & Network — usage, read/write and send/recv rates
  5. System-wide (collapsed) — overall CPU and memory

Uses ui.echart (Apache ECharts) for charts — NiceGUI 3.x dropped Highcharts.
"""

from __future__ import annotations

from nicegui import ui


def _make_area_chart(color: str, *, y_max: int | None = None, fmt: str = "{value}%") -> ui.echart:
    y_axis: dict = {"type": "value", "min": 0, "axisLabel": {"formatter": fmt}}
    if y_max is not None:
        y_axis["max"] = y_max
    return ui.echart({
        "animation": False,
        "grid": {"top": 10, "bottom": 20, "left": 50, "right": 10},
        "xAxis": {"type": "time", "show": False},
        "yAxis": y_axis,
        "series": [{
            "type": "line",
            "data": [],
            "smooth": True,
            "symbol": "none",
            "lineStyle": {"color": color, "width": 2},
            "areaStyle": {"color": color, "opacity": 0.15},
        }],
        "tooltip": {"trigger": "axis"},
    }).classes("w-full h-40")


def _make_dual_area_chart(color_a: str, color_b: str, *, fmt: str = "{value}") -> ui.echart:
    return ui.echart({
        "animation": False,
        "grid": {"top": 10, "bottom": 20, "left": 50, "right": 10},
        "xAxis": {"type": "time", "show": False},
        "yAxis": {"type": "value", "min": 0, "axisLabel": {"formatter": fmt}},
        "legend": {"show": False},
        "series": [
            {
                "name": "out",
                "type": "line", "data": [], "smooth": True, "symbol": "none",
                "lineStyle": {"color": color_a, "width": 2},
                "areaStyle": {"color": color_a, "opacity": 0.15},
            },
            {
                "name": "in",
                "type": "line", "data": [], "smooth": True, "symbol": "none",
                "lineStyle": {"color": color_b, "width": 2},
                "areaStyle": {"color": color_b, "opacity": 0.15},
            },
        ],
        "tooltip": {"trigger": "axis"},
    }).classes("w-full h-40")


def _fmt_bytes(b: int | float) -> str:
    if b >= 1024 ** 3:
        return f"{b / (1024 ** 3):.1f} GB"
    if b >= 1024 ** 2:
        return f"{b / (1024 ** 2):.1f} MB"
    if b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b:.0f} B"


def _fmt_rate(bps: float) -> str:
    return f"{_fmt_bytes(bps)}/s"


def _trim(data: list, limit: int) -> None:
    if len(data) > limit:
        del data[: len(data) - limit]


@ui.page("/metrics")
async def metrics_page() -> None:
    from hirocli.runtime.http_server import app as http_app
    from hirocli.services.metrics import MetricsCollector
    from hirocli.ui.app import create_page_layout

    create_page_layout(active_path="/metrics")

    collector: MetricsCollector | None = getattr(http_app.state, "metrics_collector", None)

    with ui.column().classes("w-full gap-6 p-6"):
        ui.label("Server Metrics").classes("text-2xl font-semibold")

        if collector is None:
            ui.label("Metrics collector is not available.").classes("text-lg opacity-60")
            return

        # ── Controls ─────────────────────────────────────────────────
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-6 p-1"):
                enable_switch = ui.switch("Enable metrics", value=collector.enabled)
                interval_slider = ui.slider(
                    min=1.0, max=10.0, step=0.5, value=collector.interval,
                ).props("label-always").classes("w-48")
                interval_label = ui.label(f"Interval: {collector.interval:.1f}s").classes("text-sm opacity-60")
                status_label = ui.label("").classes("text-sm opacity-60")

        def apply_config() -> None:
            collector.configure(enabled=enable_switch.value, interval=interval_slider.value)
            interval_label.text = f"Interval: {collector.interval:.1f}s"

        enable_switch.on_value_change(lambda _: apply_config())
        interval_slider.on_value_change(lambda _: apply_config())

        # ── Server process (primary) ─────────────────────────────────
        ui.label("Server Process").classes("text-lg font-semibold opacity-80")

        with ui.grid(columns=3).classes("w-full gap-4"):
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center gap-3 p-1"):
                    ui.icon("speed").classes("text-3xl opacity-50")
                    ui.label("Process CPU").classes("text-lg font-semibold")
                proc_cpu_label = ui.label("—").classes("text-4xl font-bold px-1")
                proc_pid_label = ui.label("").classes("text-sm opacity-60 px-1")
                proc_cpu_chart = _make_area_chart("#FF9800", y_max=100)

            with ui.card().classes("w-full"):
                with ui.row().classes("items-center gap-3 p-1"):
                    ui.icon("memory").classes("text-3xl opacity-50")
                    ui.label("Process Memory (RSS)").classes("text-lg font-semibold")
                proc_rss_label = ui.label("—").classes("text-4xl font-bold px-1")
                proc_vms_label = ui.label("").classes("text-sm opacity-60 px-1")
                proc_rss_chart = _make_area_chart("#E91E63", y_max=None, fmt="{value} MB")

            with ui.card().classes("w-full"):
                with ui.row().classes("items-center gap-3 p-1"):
                    ui.icon("hub").classes("text-3xl opacity-50")
                    ui.label("Threads").classes("text-lg font-semibold")
                proc_threads_label = ui.label("—").classes("text-4xl font-bold px-1")
                ui.label("").classes("text-sm opacity-60 px-1")
                proc_threads_chart = _make_area_chart("#9C27B0", y_max=None, fmt="{value}")

        # ── Channel plugins ──────────────────────────────────────────
        ui.label("Channel Plugins").classes("text-lg font-semibold opacity-80")

        children_columns = [
            {"name": "name", "label": "Channel", "field": "name", "align": "left"},
            {"name": "pid", "label": "PID", "field": "pid", "align": "center"},
            {"name": "alive", "label": "Status", "field": "alive", "align": "center"},
            {"name": "cpu", "label": "CPU %", "field": "cpu", "align": "right"},
            {"name": "rss", "label": "RSS", "field": "rss", "align": "right"},
            {"name": "threads", "label": "Threads", "field": "threads", "align": "right"},
        ]
        children_table = ui.table(
            columns=children_columns, rows=[], row_key="name",
        ).classes("w-full")
        children_total_label = ui.label("").classes("text-sm opacity-60")

        # ── Disk & Network ───────────────────────────────────────────
        ui.label("Disk & Network").classes("text-lg font-semibold opacity-80")

        with ui.grid(columns=2).classes("w-full gap-4"):
            # Disk
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center gap-3 p-1"):
                    ui.icon("storage").classes("text-3xl opacity-50")
                    ui.label("Disk Usage").classes("text-lg font-semibold")
                disk_label = ui.label("—").classes("text-4xl font-bold px-1")
                disk_detail_label = ui.label("").classes("text-sm opacity-60 px-1")
                disk_rate_label = ui.label("").classes("text-sm opacity-60 px-1")
                disk_chart = _make_dual_area_chart("#00BCD4", "#009688", fmt="{value} KB/s")

            # Network
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center gap-3 p-1"):
                    ui.icon("wifi").classes("text-3xl opacity-50")
                    ui.label("Network I/O").classes("text-lg font-semibold")
                net_label = ui.label("—").classes("text-4xl font-bold px-1")
                net_detail_label = ui.label("").classes("text-sm opacity-60 px-1")
                net_pkt_label = ui.label("").classes("text-sm opacity-60 px-1")
                net_chart = _make_dual_area_chart("#3F51B5", "#8BC34A", fmt="{value} KB/s")

        # ── System-wide (collapsed) ──────────────────────────────────
        with ui.expansion("System-wide", icon="monitor_heart").classes("w-full"):
            with ui.grid(columns=2).classes("w-full gap-4"):
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-3 p-1"):
                        ui.icon("developer_board").classes("text-3xl opacity-50")
                        ui.label("System CPU").classes("text-lg font-semibold")
                    sys_cpu_label = ui.label("—").classes("text-4xl font-bold px-1")
                    sys_cpu_cores_label = ui.label("").classes("text-sm opacity-60 px-1")
                    sys_cpu_chart = _make_area_chart("#2196F3", y_max=100)

                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-3 p-1"):
                        ui.icon("sd_card").classes("text-3xl opacity-50")
                        ui.label("System Memory").classes("text-lg font-semibold")
                    sys_mem_label = ui.label("—").classes("text-4xl font-bold px-1")
                    sys_mem_detail_label = ui.label("").classes("text-sm opacity-60 px-1")
                    sys_mem_chart = _make_area_chart("#4CAF50", y_max=100)

        # ── Update logic ─────────────────────────────────────────────
        MAX_PTS = 60
        proc_cpu_data: list[list] = []
        proc_rss_data: list[list] = []
        proc_threads_data: list[list] = []
        disk_read_data: list[list] = []
        disk_write_data: list[list] = []
        net_sent_data: list[list] = []
        net_recv_data: list[list] = []
        sys_cpu_data: list[list] = []
        sys_mem_data: list[list] = []

        def update() -> None:
            if not collector.enabled:
                status_label.text = "Collection paused"
                return

            snap = collector.latest
            if snap is None:
                status_label.text = "Waiting for first sample..."
                return

            status_label.text = f"History: {len(collector._history)} samples"
            ts = int(snap.timestamp * 1000)

            # ── Server process ───────────────────────────────────────
            p = snap.process
            proc_cpu_label.text = f"{p.cpu_percent:.1f}%"
            proc_pid_label.text = f"PID {p.pid}"
            proc_rss_label.text = _fmt_bytes(p.rss_bytes)
            proc_vms_label.text = f"VMS: {_fmt_bytes(p.vms_bytes)}"
            proc_threads_label.text = str(p.num_threads)

            rss_mb = round(p.rss_bytes / (1024 ** 2), 1)

            proc_cpu_data.append([ts, p.cpu_percent])
            _trim(proc_cpu_data, MAX_PTS)
            proc_cpu_chart.options["series"][0]["data"] = proc_cpu_data
            proc_cpu_chart.update()

            proc_rss_data.append([ts, rss_mb])
            _trim(proc_rss_data, MAX_PTS)
            proc_rss_chart.options["series"][0]["data"] = proc_rss_data
            proc_rss_chart.update()

            proc_threads_data.append([ts, p.num_threads])
            _trim(proc_threads_data, MAX_PTS)
            proc_threads_chart.options["series"][0]["data"] = proc_threads_data
            proc_threads_chart.update()

            # ── Channel plugin children ──────────────────────────────
            total_cpu = p.cpu_percent
            total_rss = p.rss_bytes
            total_threads = p.num_threads
            rows = []
            for c in snap.children:
                rows.append({
                    "name": c.name,
                    "pid": c.pid,
                    "alive": "running" if c.alive else "stopped",
                    "cpu": f"{c.cpu_percent:.1f}%",
                    "rss": _fmt_bytes(c.rss_bytes),
                    "threads": c.num_threads,
                })
                total_cpu += c.cpu_percent
                total_rss += c.rss_bytes
                total_threads += c.num_threads
            children_table.rows = rows
            children_table.update()

            children_total_label.text = (
                f"Total (server + {len(snap.children)} plugin{'s' if len(snap.children) != 1 else ''}): "
                f"CPU {total_cpu:.1f}%  |  RSS {_fmt_bytes(total_rss)}  |  Threads {total_threads}"
            )

            # ── Disk ─────────────────────────────────────────────────
            d = snap.disk
            disk_label.text = f"{d.percent:.1f}%"
            disk_detail_label.text = (
                f"{_fmt_bytes(d.used_bytes)} used / {_fmt_bytes(d.total_bytes)} total "
                f"({_fmt_bytes(d.free_bytes)} free)"
            )
            disk_rate_label.text = f"Read: {_fmt_rate(d.read_bytes_per_sec)}  |  Write: {_fmt_rate(d.write_bytes_per_sec)}"

            read_kb = round(d.read_bytes_per_sec / 1024, 1)
            write_kb = round(d.write_bytes_per_sec / 1024, 1)
            disk_read_data.append([ts, read_kb])
            disk_write_data.append([ts, write_kb])
            _trim(disk_read_data, MAX_PTS)
            _trim(disk_write_data, MAX_PTS)
            disk_chart.options["series"][0]["data"] = disk_write_data
            disk_chart.options["series"][1]["data"] = disk_read_data
            disk_chart.update()

            # ── Network ──────────────────────────────────────────────
            n = snap.network
            net_label.text = f"{_fmt_rate(n.bytes_sent_per_sec + n.bytes_recv_per_sec)}"
            net_detail_label.text = f"Send: {_fmt_rate(n.bytes_sent_per_sec)}  |  Recv: {_fmt_rate(n.bytes_recv_per_sec)}"
            net_pkt_label.text = f"Packets: {n.packets_sent_per_sec:.0f}/s out  |  {n.packets_recv_per_sec:.0f}/s in"

            sent_kb = round(n.bytes_sent_per_sec / 1024, 1)
            recv_kb = round(n.bytes_recv_per_sec / 1024, 1)
            net_sent_data.append([ts, sent_kb])
            net_recv_data.append([ts, recv_kb])
            _trim(net_sent_data, MAX_PTS)
            _trim(net_recv_data, MAX_PTS)
            net_chart.options["series"][0]["data"] = net_sent_data
            net_chart.options["series"][1]["data"] = net_recv_data
            net_chart.update()

            # ── System-wide ──────────────────────────────────────────
            sys_cpu_label.text = f"{snap.cpu.percent:.1f}%"
            cores_str = "  ".join(f"C{i}: {v:.0f}%" for i, v in enumerate(snap.cpu.per_core))
            sys_cpu_cores_label.text = cores_str

            sys_cpu_data.append([ts, snap.cpu.percent])
            _trim(sys_cpu_data, MAX_PTS)
            sys_cpu_chart.options["series"][0]["data"] = sys_cpu_data
            sys_cpu_chart.update()

            m = snap.memory
            sys_mem_label.text = f"{m.percent:.1f}%"
            sys_mem_detail_label.text = (
                f"{_fmt_bytes(m.used_bytes)} used / {_fmt_bytes(m.total_bytes)} total "
                f"({_fmt_bytes(m.available_bytes)} available)"
            )

            sys_mem_data.append([ts, m.percent])
            _trim(sys_mem_data, MAX_PTS)
            sys_mem_chart.options["series"][0]["data"] = sys_mem_data
            sys_mem_chart.update()

        ui.timer(2.0, update)
