"""Pydantic models for system metrics snapshots."""

from __future__ import annotations

from pydantic import BaseModel


class CpuMetrics(BaseModel):
    percent: float
    per_core: list[float]

class MemoryMetrics(BaseModel):
    total_bytes: int
    used_bytes: int
    available_bytes: int
    percent: float

class ProcessMetrics(BaseModel):
    pid: int
    cpu_percent: float
    rss_bytes: int
    vms_bytes: int
    num_threads: int

class ChildProcessMetrics(BaseModel):
    name: str
    pid: int
    alive: bool
    cpu_percent: float
    rss_bytes: int
    num_threads: int

class DiskMetrics(BaseModel):
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float
    read_bytes_per_sec: float
    write_bytes_per_sec: float

class NetworkMetrics(BaseModel):
    bytes_sent_per_sec: float
    bytes_recv_per_sec: float
    packets_sent_per_sec: float
    packets_recv_per_sec: float

class MetricsSnapshot(BaseModel):
    timestamp: float
    process: ProcessMetrics
    children: list[ChildProcessMetrics]
    cpu: CpuMetrics
    memory: MemoryMetrics
    disk: DiskMetrics
    network: NetworkMetrics
