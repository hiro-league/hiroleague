"""Admin metrics for the Svelte UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from hirocli.admin.shared.formatters import fmt_bytes, fmt_rate_bps
from hirocli.admin.shared.result import Result

if TYPE_CHECKING:
    from hirocli.services.metrics import MetricsCollector, MetricsSnapshot


@dataclass(frozen=True)
class MetricsChartScalars:
    """One timestep of numeric values for client-side ECharts series."""

    ts_ms: int
    proc_cpu: float
    proc_rss_mb: float
    proc_threads: int
    disk_read_kb: float
    disk_write_kb: float
    net_sent_kb: float
    net_recv_kb: float
    sys_cpu: float
    sys_mem_pct: float


@dataclass(frozen=True)
class MetricsUiFrame:
    """Precomputed strings + table rows for one paint cycle."""

    chart: MetricsChartScalars
    process_cpu_label: str
    process_pid_caption: str
    process_rss_label: str
    process_vms_caption: str
    process_threads_label: str
    children_rows: list[dict[str, Any]]
    children_total_caption: str
    disk_percent_label: str
    disk_detail_caption: str
    disk_rate_caption: str
    net_total_rate_label: str
    net_detail_caption: str
    net_packets_caption: str
    sys_cpu_label: str
    sys_cpu_cores_caption: str
    sys_mem_label: str
    sys_mem_detail_caption: str


@dataclass(frozen=True)
class MetricsTickPayload:
    """What the timer callback needs each cycle."""

    status_text: str
    frame: MetricsUiFrame | None


@dataclass(frozen=True)
class MetricsConfigState:
    """Effective collector settings after configure()."""

    enabled: bool
    interval: float


class MetricsAdminService:
    """Facade over MetricsCollector for HiroAdmin v2 (testable, no globals)."""

    def prepare_tick(self, collector: "MetricsCollector") -> MetricsTickPayload:
        if not collector.enabled:
            return MetricsTickPayload(status_text="Collection paused", frame=None)
        snap = collector.latest
        if snap is None:
            return MetricsTickPayload(status_text="Waiting for first sample...", frame=None)
        history_len = len(collector.history)
        status = f"History: {history_len} samples"
        return MetricsTickPayload(status_text=status, frame=self.build_ui_frame(snap))

    def build_ui_frame(self, snap: "MetricsSnapshot") -> MetricsUiFrame:
        ts = int(snap.timestamp * 1000)
        p = snap.process
        rss_mb = round(p.rss_bytes / (1024**2), 1)

        total_cpu = p.cpu_percent
        total_rss = p.rss_bytes
        total_threads = p.num_threads
        rows: list[dict[str, Any]] = []
        for c in snap.children:
            rows.append(
                {
                    "name": c.name,
                    "pid": c.pid,
                    "alive": "running" if c.alive else "stopped",
                    "cpu": f"{c.cpu_percent:.1f}%",
                    "rss": fmt_bytes(c.rss_bytes),
                    "threads": c.num_threads,
                }
            )
            total_cpu += c.cpu_percent
            total_rss += c.rss_bytes
            total_threads += c.num_threads

        n_plugins = len(snap.children)
        plug_word = "plugin" if n_plugins == 1 else "plugins"
        children_total = (
            f"Total (server + {n_plugins} {plug_word}): "
            f"CPU {total_cpu:.1f}%  |  RSS {fmt_bytes(total_rss)}  |  Threads {total_threads}"
        )

        d = snap.disk
        n = snap.network
        m = snap.memory
        cores_str = "  ".join(f"C{i}: {v:.0f}%" for i, v in enumerate(snap.cpu.per_core))

        chart = MetricsChartScalars(
            ts_ms=ts,
            proc_cpu=p.cpu_percent,
            proc_rss_mb=rss_mb,
            proc_threads=p.num_threads,
            disk_read_kb=round(d.read_bytes_per_sec / 1024, 1),
            disk_write_kb=round(d.write_bytes_per_sec / 1024, 1),
            net_sent_kb=round(n.bytes_sent_per_sec / 1024, 1),
            net_recv_kb=round(n.bytes_recv_per_sec / 1024, 1),
            sys_cpu=snap.cpu.percent,
            sys_mem_pct=m.percent,
        )

        return MetricsUiFrame(
            chart=chart,
            process_cpu_label=f"{p.cpu_percent:.1f}%",
            process_pid_caption=f"PID {p.pid}",
            process_rss_label=fmt_bytes(p.rss_bytes),
            process_vms_caption=f"VMS: {fmt_bytes(p.vms_bytes)}",
            process_threads_label=str(p.num_threads),
            children_rows=rows,
            children_total_caption=children_total,
            disk_percent_label=f"{d.percent:.1f}%",
            disk_detail_caption=(
                f"{fmt_bytes(d.used_bytes)} used / {fmt_bytes(d.total_bytes)} total "
                f"({fmt_bytes(d.free_bytes)} free)"
            ),
            disk_rate_caption=(
                f"Read: {fmt_rate_bps(d.read_bytes_per_sec)}  |  "
                f"Write: {fmt_rate_bps(d.write_bytes_per_sec)}"
            ),
            net_total_rate_label=fmt_rate_bps(n.bytes_sent_per_sec + n.bytes_recv_per_sec),
            net_detail_caption=(
                f"Send: {fmt_rate_bps(n.bytes_sent_per_sec)}  |  "
                f"Recv: {fmt_rate_bps(n.bytes_recv_per_sec)}"
            ),
            net_packets_caption=(
                f"Packets: {n.packets_sent_per_sec:.0f}/s out  |  "
                f"{n.packets_recv_per_sec:.0f}/s in"
            ),
            sys_cpu_label=f"{snap.cpu.percent:.1f}%",
            sys_cpu_cores_caption=cores_str,
            sys_mem_label=f"{m.percent:.1f}%",
            sys_mem_detail_caption=(
                f"{fmt_bytes(m.used_bytes)} used / {fmt_bytes(m.total_bytes)} total "
                f"({fmt_bytes(m.available_bytes)} available)"
            ),
        )

    def configure(
        self,
        collector: "MetricsCollector",
        *,
        enabled: bool | None = None,
        interval: float | None = None,
    ) -> Result[MetricsConfigState]:
        try:
            collector.configure(enabled=enabled, interval=interval)
        except Exception as exc:
            return Result(ok=False, error=str(exc))
        return Result(
            ok=True,
            data=MetricsConfigState(enabled=collector.enabled, interval=collector.interval),
        )
