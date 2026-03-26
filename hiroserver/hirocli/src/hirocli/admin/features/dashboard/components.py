"""Dashboard UI — stat grid from DashboardData (NiceGUI only here)."""

from __future__ import annotations

from nicegui import ui

from hirocli.admin.features.dashboard.service import DashboardData
from hirocli.admin.shared.ui.empty_state import empty_state
from hirocli.admin.shared.ui.stat_card import stat_card


def render_dashboard_overview(data: DashboardData) -> None:
    """Six stat cards matching legacy dashboard layout and gateway status logic."""
    if not data.gateway_running:
        gw_label, gw_icon, gw_ok = "Stopped", "wifi_off", False
    elif data.gateway_desktop_connected:
        gw_label, gw_icon, gw_ok = "Connected", "wifi", True
    elif data.gateway_auth_error:
        gw_label, gw_icon, gw_ok = "Auth Error", "wifi_off", False
    else:
        gw_label, gw_icon, gw_ok = "Running", "wifi", None

    with ui.grid(columns=3).classes("w-full gap-4"):
        stat_card("Total workspaces", str(data.total_workspaces), "workspaces")
        stat_card("Running workspaces", str(data.running_workspaces), "activity")
        stat_card("Gateway", gw_label, gw_icon, ok=gw_ok)
        stat_card("Paired devices", str(data.total_devices), "smartphone")
        stat_card("Installed channels", str(data.total_channels), "extension")
        stat_card("Enabled channels", str(data.enabled_channels), "check_circle")


def maybe_render_no_workspaces_hint(data: DashboardData) -> None:
    """Extra empty hint when the registry has no workspaces (guidelines §2.4 empty state)."""
    if data.total_workspaces == 0:
        empty_state(
            message="No workspaces registered yet. Create one from Workspaces (v2 or legacy).",
            icon="folder_open",
        )
