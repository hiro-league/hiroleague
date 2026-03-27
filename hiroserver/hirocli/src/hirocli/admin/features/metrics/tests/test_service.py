"""MetricsAdminService — snapshot → UI frame, configure, tick payload."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hirocli.admin.features.metrics.service import MetricsAdminService
from hirocli.services.metrics.models import (
    ChildProcessMetrics,
    CpuMetrics,
    DiskMetrics,
    MemoryMetrics,
    MetricsSnapshot,
    NetworkMetrics,
    ProcessMetrics,
)


def _sample_snapshot() -> MetricsSnapshot:
    return MetricsSnapshot(
        timestamp=1_700_000_000.0,
        process=ProcessMetrics(
            pid=1234,
            cpu_percent=12.5,
            rss_bytes=100 * 1024 * 1024,
            vms_bytes=200 * 1024 * 1024,
            num_threads=8,
        ),
        children=[
            ChildProcessMetrics(
                name="plugin-a",
                pid=5678,
                alive=True,
                cpu_percent=3.0,
                rss_bytes=10 * 1024 * 1024,
                num_threads=2,
            )
        ],
        cpu=CpuMetrics(percent=45.0, per_core=[40.0, 50.0]),
        memory=MemoryMetrics(
            total_bytes=16 * 1024**3,
            used_bytes=8 * 1024**3,
            available_bytes=8 * 1024**3,
            percent=50.0,
        ),
        disk=DiskMetrics(
            total_bytes=500 * 1024**3,
            used_bytes=250 * 1024**3,
            free_bytes=250 * 1024**3,
            percent=50.0,
            read_bytes_per_sec=1024,
            write_bytes_per_sec=2048,
        ),
        network=NetworkMetrics(
            bytes_sent_per_sec=4096,
            bytes_recv_per_sec=8192,
            packets_sent_per_sec=10.0,
            packets_recv_per_sec=20.0,
        ),
    )


def test_build_ui_frame_process_and_totals() -> None:
    svc = MetricsAdminService()
    snap = _sample_snapshot()
    frame = svc.build_ui_frame(snap)

    assert frame.process_cpu_label == "12.5%"
    assert frame.process_pid_caption == "PID 1234"
    assert "100.0 MB" in frame.process_rss_label or "100.0 MB" == frame.process_rss_label
    assert frame.process_threads_label == "8"
    assert len(frame.children_rows) == 1
    assert frame.children_rows[0]["name"] == "plugin-a"
    assert "Total (server + 1 plugin):" in frame.children_total_caption
    assert frame.chart.ts_ms == 1_700_000_000_000
    assert frame.chart.proc_rss_mb == pytest.approx(100.0)


def test_prepare_tick_paused_no_frame() -> None:
    svc = MetricsAdminService()
    col = MagicMock()
    col.enabled = False
    payload = svc.prepare_tick(col)
    assert payload.status_text == "Collection paused"
    assert payload.frame is None


def test_prepare_tick_waiting_no_snapshot() -> None:
    svc = MetricsAdminService()
    col = MagicMock()
    col.enabled = True
    col.latest = None
    col.history = []
    payload = svc.prepare_tick(col)
    assert payload.frame is None
    assert "Waiting" in payload.status_text


def test_prepare_tick_with_snapshot() -> None:
    svc = MetricsAdminService()
    snap = _sample_snapshot()
    col = MagicMock()
    col.enabled = True
    col.latest = snap
    col.history = [snap]
    payload = svc.prepare_tick(col)
    assert payload.frame is not None
    assert "History: 1 samples" == payload.status_text


def test_configure_success() -> None:
    svc = MetricsAdminService()
    col = MagicMock()
    col.enabled = False
    col.interval = 2.0
    col.configure = MagicMock()

    result = svc.configure(col, enabled=True, interval=3.5)
    assert result.ok
    assert result.data is not None
    col.configure.assert_called_once_with(enabled=True, interval=3.5)


def test_configure_exception() -> None:
    svc = MetricsAdminService()
    col = MagicMock()
    col.configure = MagicMock(side_effect=RuntimeError("boom"))

    result = svc.configure(col, enabled=True)
    assert not result.ok
    assert result.error == "boom"
