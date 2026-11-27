"""Where a person opens the admin, and the "Hiro is running" panel that says so (issue 448).

The admin listens on 127.0.0.1 at its workspace's admin port. When the front door (Caddy, set up by `hiro service
install`) serves the core's names, the LAN reaches it at ``http://<core name>.local`` too. Every start that has a
terminal prints the panel once the admin answers: a background start, a foreground one (above its logs) and the
service's install. A browser opens only once: at the end of the service's first install, never at boot.
"""

from __future__ import annotations

import os
import sys
import webbrowser

from rich.console import Console
from rich.panel import Panel

from hiro_commons.log import Logger

from .domain.front_door import ENV_FRONT_DOOR

log = Logger.get("CLI.ADMIN")


def local_url(admin_port: int) -> str:
    return f"http://localhost:{admin_port}"


def lan_url(site_domain: str, *, front_door: bool | None = None) -> str | None:
    """The admin's LAN address when the front door serves the core's names (None otherwise). ``front_door`` None:
    this process's own environment says (the service gives its server HIRO_FRONT_DOOR)."""
    serves = bool(os.environ.get(ENV_FRONT_DOOR, "").strip()) if front_door is None else front_door
    return f"http://{site_domain}" if serves and site_domain else None


def print_ready_panel(console: Console, admin_port: int, lan: str | None = None) -> None:
    """The friendly, clickable "Hiro is running" panel."""
    lines = [f"🌐  Admin dashboard:  [bold cyan]{local_url(admin_port)}[/bold cyan]"]
    if lan:
        lines.append(f"🏠  On your network:  [bold cyan]{lan}[/bold cyan]")
    console.print(Panel("\n".join(lines), title="[green]Hiro is running[/green]", border_style="green", expand=False))


def can_open_browser() -> bool:
    """A desktop to open a browser on: Windows and macOS always; Linux only with a display (never over ssh alone)."""
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def open_admin(url: str) -> None:
    if not can_open_browser():
        return
    try:
        webbrowser.open(url)
    except webbrowser.Error as exc:  # no browser registered: the panel still says where the admin is
        log.warning("⚠️ Could not open a browser on the admin", url=url, error=str(exc))
