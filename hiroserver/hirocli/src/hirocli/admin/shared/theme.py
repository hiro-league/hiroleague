"""Quasar brand colors via NiceGUI — single place for admin-wide palette."""

from __future__ import annotations


def apply_theme() -> None:
    """Set app-wide Quasar brand colors (CSS variables --q-primary, etc.)."""
    from nicegui import app as nicegui_app

    # NiceGUI 3.6+ exposes app.colors; keep defaults if older.
    colors = getattr(nicegui_app, "colors", None)
    if callable(colors):
        colors(
            primary="#5898d4",
            secondary="#26a69a",
            accent="#9c27b0",
            positive="#21ba45",
            negative="#c10015",
            info="#31ccec",
            warning="#f2c037",
        )


# ECharts line/area series colors (not Quasar widgets — hex lives here per admin guidelines).
METRICS_ECHART_COLORS: dict[str, str] = {
    "proc_cpu": "#f2c037",
    "proc_rss": "#e91e63",
    "proc_threads": "#9c27b0",
    "disk_write": "#26a69a",
    "disk_read": "#31ccec",
    "net_sent": "#5898d4",
    "net_recv": "#8bc34a",
    "sys_cpu": "#5898d4",
    "sys_mem": "#21ba45",
}
