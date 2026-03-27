"""Shared formatting helpers (bytes, rates, bounded series) for admin UI."""

from __future__ import annotations

__all__ = ["fmt_bytes", "fmt_rate_bps", "trim_series_in_place"]


def fmt_bytes(b: int | float) -> str:
    """Human-readable byte size (B / KB / MB / GB)."""
    if b >= 1024**3:
        return f"{b / (1024**3):.1f} GB"
    if b >= 1024**2:
        return f"{b / (1024**2):.1f} MB"
    if b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b:.0f} B"


def fmt_rate_bps(bps: float) -> str:
    """Throughput as N B/s, N KB/s, etc."""
    return f"{fmt_bytes(bps)}/s"


def trim_series_in_place(data: list, limit: int) -> None:
    """Drop oldest points so len(data) <= limit (charts use this for sliding windows)."""
    if len(data) > limit:
        del data[: len(data) - limit]
