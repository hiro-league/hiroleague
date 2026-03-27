"""Shared formatters — bytes, rates, series trim."""

from __future__ import annotations

from hirocli.admin.shared.formatters import fmt_bytes, fmt_rate_bps, trim_series_in_place


def test_fmt_bytes_scales() -> None:
    assert fmt_bytes(500) == "500 B"
    assert "KB" in fmt_bytes(2048)
    assert "MB" in fmt_bytes(3 * 1024**2)
    assert "GB" in fmt_bytes(2 * 1024**3)


def test_fmt_rate_bps() -> None:
    assert fmt_rate_bps(1024).endswith("/s")


def test_trim_series_in_place() -> None:
    data = [[1, 1], [2, 2], [3, 3], [4, 4]]
    trim_series_in_place(data, 2)
    assert data == [[3, 3], [4, 4]]
