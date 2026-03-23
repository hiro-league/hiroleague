"""MetricsCollector — async service that samples system metrics on a timer.

Runs as a peer of ChannelManager / CommunicationManager inside the server's
asyncio.gather.  Collection happens in a thread via asyncio.to_thread so
psutil's blocking calls never stall the event loop.

The collector is safe to instantiate even when disabled — its run() loop
simply sleeps until enabled.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from collections import deque
from collections.abc import Callable

import psutil
from hiro_commons.log import Logger

from .models import (
    ChildProcessMetrics,
    CpuMetrics,
    DiskMetrics,
    MemoryMetrics,
    MetricsSnapshot,
    NetworkMetrics,
    ProcessMetrics,
)

log = Logger.get("METRICS")

MIN_INTERVAL = 1.0

ChildPidProvider = Callable[[], list[tuple[str, subprocess.Popen]]]


class MetricsCollector:

    def __init__(
        self,
        enabled: bool = False,
        interval: float = 2.0,
        history_size: int = 1800,
    ) -> None:
        self._enabled = enabled
        self._interval = max(interval, MIN_INTERVAL)
        self._history: deque[MetricsSnapshot] = deque(maxlen=history_size)
        self._history_size = history_size
        self._latest: MetricsSnapshot | None = None
        self._subscribers: list[asyncio.Queue[MetricsSnapshot]] = []
        self._child_pid_provider: ChildPidProvider | None = None

        # Seed cpu_percent so the first real reading isn't always 0
        psutil.cpu_percent(percpu=True)
        self._process = psutil.Process()
        self._process.cpu_percent()

        # Previous counters for rate calculation (disk and network)
        self._prev_disk = psutil.disk_io_counters()
        self._prev_net = psutil.net_io_counters()
        self._prev_time = time.monotonic()

        # Seeded psutil.Process handles for child processes (keyed by PID)
        self._child_handles: dict[int, psutil.Process] = {}

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def interval(self) -> float:
        return self._interval

    @property
    def latest(self) -> MetricsSnapshot | None:
        return self._latest

    @property
    def history(self) -> list[MetricsSnapshot]:
        return list(self._history)

    # ------------------------------------------------------------------
    # Child process provider
    # ------------------------------------------------------------------

    def set_child_pid_provider(self, provider: ChildPidProvider) -> None:
        self._child_pid_provider = provider

    # ------------------------------------------------------------------
    # Runtime control
    # ------------------------------------------------------------------

    def enable(self) -> None:
        self._enabled = True
        log.info("Metrics collection enabled", interval=self._interval)

    def disable(self) -> None:
        self._enabled = False
        self._latest = None
        log.info("Metrics collection disabled")

    def configure(
        self,
        enabled: bool | None = None,
        interval: float | None = None,
        history_size: int | None = None,
    ) -> dict:
        """Apply runtime configuration changes. Returns the effective config."""
        if enabled is not None:
            self._enabled = enabled
        if interval is not None:
            self._interval = max(interval, MIN_INTERVAL)
        if history_size is not None and history_size != self._history_size:
            self._history_size = history_size
            old = list(self._history)
            self._history = deque(old, maxlen=history_size)

        log.info(
            "Metrics config updated",
            enabled=self._enabled,
            interval=self._interval,
            history_size=self._history_size,
        )
        return self.status()

    def status(self) -> dict:
        return {
            "enabled": self._enabled,
            "interval": self._interval,
            "history_size": self._history_size,
            "history_length": len(self._history),
            "subscribers": len(self._subscribers),
        }

    # ------------------------------------------------------------------
    # Subscriber management (for live push to UI / WebSocket consumers)
    # ------------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue[MetricsSnapshot]:
        q: asyncio.Queue[MetricsSnapshot] = asyncio.Queue(maxsize=100)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[MetricsSnapshot]) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main collection loop — add to asyncio.gather in server_process."""
        log.info(
            "✅ Metrics collector started",
            enabled=self._enabled,
            interval=self._interval,
        )
        while True:
            if self._enabled:
                try:
                    snapshot = await asyncio.to_thread(self._collect)
                    self._latest = snapshot
                    self._history.append(snapshot)
                    self._broadcast(snapshot)
                except Exception:
                    log.error("Metrics collection failed", exc_info=True)

            await asyncio.sleep(self._interval)

    # ------------------------------------------------------------------
    # Collection (runs in thread)
    # ------------------------------------------------------------------

    def _collect(self) -> MetricsSnapshot:
        now_mono = time.monotonic()
        dt = max(now_mono - self._prev_time, 0.001)

        # Server process
        proc = self._process
        proc_cpu = proc.cpu_percent()
        mem_info = proc.memory_info()

        # Child processes (channel plugins)
        children = self._collect_children()

        # System CPU
        cpu_pcts = psutil.cpu_percent(percpu=True)
        cpu_avg = sum(cpu_pcts) / len(cpu_pcts) if cpu_pcts else 0.0

        # System memory
        mem = psutil.virtual_memory()

        # Disk I/O rates
        disk_counters = psutil.disk_io_counters()
        # psutil.disk_usage needs a mount point — "C:\\" on Windows, "/" elsewhere
        disk_root = "C:\\" if sys.platform == "win32" else "/"
        disk_usage = psutil.disk_usage(disk_root)
        disk_read_rate = 0.0
        disk_write_rate = 0.0
        if disk_counters and self._prev_disk:
            disk_read_rate = (disk_counters.read_bytes - self._prev_disk.read_bytes) / dt
            disk_write_rate = (disk_counters.write_bytes - self._prev_disk.write_bytes) / dt
        self._prev_disk = disk_counters

        # Network I/O rates
        net_counters = psutil.net_io_counters()
        net_sent_rate = 0.0
        net_recv_rate = 0.0
        pkt_sent_rate = 0.0
        pkt_recv_rate = 0.0
        if net_counters and self._prev_net:
            net_sent_rate = (net_counters.bytes_sent - self._prev_net.bytes_sent) / dt
            net_recv_rate = (net_counters.bytes_recv - self._prev_net.bytes_recv) / dt
            pkt_sent_rate = (net_counters.packets_sent - self._prev_net.packets_sent) / dt
            pkt_recv_rate = (net_counters.packets_recv - self._prev_net.packets_recv) / dt
        self._prev_net = net_counters
        self._prev_time = now_mono

        return MetricsSnapshot(
            timestamp=time.time(),
            process=ProcessMetrics(
                pid=proc.pid,
                cpu_percent=round(proc_cpu, 1),
                rss_bytes=mem_info.rss,
                vms_bytes=mem_info.vms,
                num_threads=proc.num_threads(),
            ),
            children=children,
            cpu=CpuMetrics(
                percent=round(cpu_avg, 1),
                per_core=[round(c, 1) for c in cpu_pcts],
            ),
            memory=MemoryMetrics(
                total_bytes=mem.total,
                used_bytes=mem.used,
                available_bytes=mem.available,
                percent=round(mem.percent, 1),
            ),
            disk=DiskMetrics(
                total_bytes=disk_usage.total,
                used_bytes=disk_usage.used,
                free_bytes=disk_usage.free,
                percent=round(disk_usage.percent, 1),
                read_bytes_per_sec=round(disk_read_rate, 0),
                write_bytes_per_sec=round(disk_write_rate, 0),
            ),
            network=NetworkMetrics(
                bytes_sent_per_sec=round(net_sent_rate, 0),
                bytes_recv_per_sec=round(net_recv_rate, 0),
                packets_sent_per_sec=round(pkt_sent_rate, 1),
                packets_recv_per_sec=round(pkt_recv_rate, 1),
            ),
        )

    def _collect_children(self) -> list[ChildProcessMetrics]:
        if self._child_pid_provider is None:
            return []

        results: list[ChildProcessMetrics] = []
        for name, popen in self._child_pid_provider():
            pid = popen.pid
            try:
                handle = self._child_handles.get(pid)
                if handle is None:
                    handle = psutil.Process(pid)
                    # Seed cpu_percent for this child
                    handle.cpu_percent()
                    self._child_handles[pid] = handle

                results.append(ChildProcessMetrics(
                    name=name,
                    pid=pid,
                    alive=handle.is_running(),
                    cpu_percent=round(handle.cpu_percent(), 1),
                    rss_bytes=handle.memory_info().rss,
                    num_threads=handle.num_threads(),
                ))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                results.append(ChildProcessMetrics(
                    name=name, pid=pid, alive=False,
                    cpu_percent=0.0, rss_bytes=0, num_threads=0,
                ))

        # Clean up handles for PIDs no longer in the provider list
        active_pids = {r.pid for r in results}
        stale = [p for p in self._child_handles if p not in active_pids]
        for p in stale:
            del self._child_handles[p]

        return results

    def _broadcast(self, snapshot: MetricsSnapshot) -> None:
        dead: list[asyncio.Queue] = []
        for q in self._subscribers:
            try:
                q.put_nowait(snapshot)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)
