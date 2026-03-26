"""Sidebar navigation entries: (group, label, icon, path). group=None => section header.

Paths are full browser paths under the v2 mount (see admin/router.py).
"""

from __future__ import annotations

from typing import NamedTuple

from hirocli.admin.router import V2_ROOT


class NavItem(NamedTuple):
    """One row in the sidebar: section header (path None) or clickable link."""

    group: str | None
    label: str
    icon: str | None
    path: str | None


NAV: list[NavItem] = [
    NavItem(None, "Dashboard", None, None),
    NavItem("Dashboard", "Dashboard", "dashboard", V2_ROOT),
    NavItem("Dashboard", "Metrics", "analytics", "/v2/metrics"),
    NavItem(None, "Server", None, None),
    NavItem("Server", "Workspaces", "storage", "/v2/workspaces"),
    NavItem("Server", "Channels", "cable", "/v2/channels"),
    NavItem("Server", "Gateways", "router", "/v2/gateways"),
    NavItem("Server", "Agents", "smart_toy", "/v2/agents"),
    NavItem(None, "Nodes / Devices", None, None),
    NavItem("Nodes / Devices", "Devices", "devices", "/v2/devices"),
    NavItem("Nodes / Devices", "Chats", "chat", "/v2/chats"),
    NavItem(None, "Configuration", None, None),
    NavItem("Configuration", "Logs", "article", "/v2/logs"),
]
