"""Sidebar navigation entries: (group, label, icon, path). group=None => section header.

Paths are full browser paths on the admin router (see admin/router.py).
"""

from __future__ import annotations

from typing import NamedTuple

from hirocli.admin.router import ADMIN_ROOT


class NavItem(NamedTuple):
    """One row in the sidebar: section header (path None) or clickable link."""

    group: str | None
    label: str
    icon: str | None
    path: str | None


NAV: list[NavItem] = [
    NavItem(None, "Dashboard", None, None),
    NavItem("Dashboard", "Dashboard", "dashboard", ADMIN_ROOT),
    NavItem("Dashboard", "Metrics", "analytics", "/metrics"),
    NavItem(None, "Server", None, None),
    NavItem("Server", "Workspaces", "storage", "/workspaces"),
    NavItem("Server", "Channels", "cable", "/channels"),
    NavItem("Server", "Gateways", "router", "/gateways"),
    NavItem(None, "AI Models", None, None),
    NavItem("AI Models", "Catalog", "menu_book", "/catalog"),
    NavItem("AI Models", "Active Providers", "vpn_key", "/providers"),
    NavItem(None, "Communication", None, None),
    NavItem("Communication", "Characters", "face", "/characters"),
    NavItem("Communication", "Chat channels", "chat", "/chats"),
    NavItem(None, "Nodes / Devices", None, None),
    NavItem("Nodes / Devices", "Devices", "devices", "/devices"),
    NavItem(None, "Configuration", None, None),
    NavItem("Configuration", "Logs", "article", "/logs"),
]
