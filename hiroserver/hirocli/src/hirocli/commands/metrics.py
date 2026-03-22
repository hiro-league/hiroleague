"""Metrics CLI subcommands — view server resource metrics from the terminal.

Commands:
  hirocli metrics status   — show collector config and state
  hirocli metrics snapshot — print the latest metrics snapshot
  hirocli metrics live     — live-updating dashboard (Ctrl+C to stop)
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Optional

import typer
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text

from ..domain.workspace import WorkspaceError, resolve_workspace
from ..domain.config import load_config


def _api_url(workspace: str | None, path: str) -> str:
    """Build a full HTTP URL for a metrics endpoint."""
    entry, _ = resolve_workspace(workspace)
    config = load_config(entry.path)
    return f"http://127.0.0.1:{config.http_port}{path}"


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def _fmt_bytes(b: int | float) -> str:
    if b >= 1024 ** 3:
        return f"{b / (1024 ** 3):.1f} GB"
    if b >= 1024 ** 2:
        return f"{b / (1024 ** 2):.1f} MB"
    if b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b:.0f} B"


def _fmt_rate(bps: float) -> str:
    return f"{_fmt_bytes(bps)}/s"


def _build_snapshot_display(snap: dict) -> Table:
    """Build a rich Table from a metrics snapshot dict."""
    outer = Table(show_header=False, box=None, padding=(0, 0))

    # Server process
    p = snap.get("process", {})
    proc_table = Table(title="Server Process", show_header=True, min_width=40)
    proc_table.add_column("Metric", style="bold")
    proc_table.add_column("Value", justify="right")
    proc_table.add_row("PID", str(p.get("pid", "—")))
    proc_table.add_row("CPU", f"{p.get('cpu_percent', 0):.1f}%")
    proc_table.add_row("RSS", _fmt_bytes(p.get("rss_bytes", 0)))
    proc_table.add_row("VMS", _fmt_bytes(p.get("vms_bytes", 0)))
    proc_table.add_row("Threads", str(p.get("num_threads", 0)))

    # Channel plugins
    children = snap.get("children", [])
    child_table = Table(title="Channel Plugins", show_header=True, min_width=50)
    child_table.add_column("Channel", style="cyan")
    child_table.add_column("PID", justify="center")
    child_table.add_column("Status", justify="center")
    child_table.add_column("CPU", justify="right")
    child_table.add_column("RSS", justify="right")
    child_table.add_column("Threads", justify="right")

    total_cpu = p.get("cpu_percent", 0)
    total_rss = p.get("rss_bytes", 0)
    total_threads = p.get("num_threads", 0)

    for c in children:
        alive = c.get("alive", False)
        status = "[green]running[/green]" if alive else "[red]stopped[/red]"
        child_table.add_row(
            c.get("name", "?"),
            str(c.get("pid", "—")),
            status,
            f"{c.get('cpu_percent', 0):.1f}%",
            _fmt_bytes(c.get("rss_bytes", 0)),
            str(c.get("num_threads", 0)),
        )
        total_cpu += c.get("cpu_percent", 0)
        total_rss += c.get("rss_bytes", 0)
        total_threads += c.get("num_threads", 0)

    if not children:
        child_table.add_row("[dim]no plugins[/dim]", "", "", "", "", "")

    child_table.add_row(
        "[bold]Total[/bold]", "", "",
        f"[bold]{total_cpu:.1f}%[/bold]",
        f"[bold]{_fmt_bytes(total_rss)}[/bold]",
        f"[bold]{total_threads}[/bold]",
    )

    # System
    cpu = snap.get("cpu", {})
    mem = snap.get("memory", {})
    sys_table = Table(title="System", show_header=True, min_width=40)
    sys_table.add_column("Metric", style="bold")
    sys_table.add_column("Value", justify="right")
    sys_table.add_row("CPU", f"{cpu.get('percent', 0):.1f}%")
    cores = cpu.get("per_core", [])
    if cores:
        core_str = "  ".join(f"C{i}:{v:.0f}%" for i, v in enumerate(cores))
        sys_table.add_row("Cores", core_str)
    sys_table.add_row("Memory", f"{mem.get('percent', 0):.1f}%")
    sys_table.add_row(
        "Mem detail",
        f"{_fmt_bytes(mem.get('used_bytes', 0))} / {_fmt_bytes(mem.get('total_bytes', 0))}",
    )

    # Disk
    disk = snap.get("disk", {})
    sys_table.add_row("Disk", f"{disk.get('percent', 0):.1f}%")
    sys_table.add_row(
        "Disk I/O",
        f"R: {_fmt_rate(disk.get('read_bytes_per_sec', 0))}  W: {_fmt_rate(disk.get('write_bytes_per_sec', 0))}",
    )

    # Network
    net = snap.get("network", {})
    sys_table.add_row(
        "Network",
        f"Send: {_fmt_rate(net.get('bytes_sent_per_sec', 0))}  Recv: {_fmt_rate(net.get('bytes_recv_per_sec', 0))}",
    )
    sys_table.add_row(
        "Packets",
        f"{net.get('packets_sent_per_sec', 0):.0f}/s out  {net.get('packets_recv_per_sec', 0):.0f}/s in",
    )

    outer.add_row(proc_table)
    outer.add_row("")
    outer.add_row(child_table)
    outer.add_row("")
    outer.add_row(sys_table)
    return outer


def register(metrics_app: typer.Typer, console: Console) -> None:
    """Register metrics subcommands."""

    @metrics_app.command("status")
    def metrics_status(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace name (default: registry default).",
        ),
    ) -> None:
        """Show metrics collector configuration and state."""
        try:
            url = _api_url(workspace, "/metrics/status")
            data = _get_json(url)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        except Exception as exc:
            console.print(f"[red]Cannot reach server:[/red] {exc}")
            raise typer.Exit(1)

        table = Table(title="Metrics Collector Status", show_header=False, min_width=35)
        table.add_column("Key", style="bold")
        table.add_column("Value")

        enabled = data.get("enabled", False)
        table.add_row("Enabled", "[green]yes[/green]" if enabled else "[red]no[/red]")
        table.add_row("Interval", f"{data.get('interval', '?')}s")
        table.add_row("History size", str(data.get("history_size", "?")))
        table.add_row("History length", str(data.get("history_length", "?")))
        table.add_row("Subscribers", str(data.get("subscribers", "?")))
        console.print(table)

    @metrics_app.command("snapshot")
    def metrics_snapshot(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace name (default: registry default).",
        ),
    ) -> None:
        """Print the latest metrics snapshot."""
        try:
            url = _api_url(workspace, "/metrics")
            snap = _get_json(url)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                console.print("[yellow]Metrics collection is disabled. Enable with --metrics flag or admin UI.[/yellow]")
            elif exc.code == 503:
                console.print("[yellow]No metrics collected yet — waiting for first sample.[/yellow]")
            else:
                console.print(f"[red]Server error:[/red] {exc}")
            raise typer.Exit(1)
        except Exception as exc:
            console.print(f"[red]Cannot reach server:[/red] {exc}")
            raise typer.Exit(1)

        console.print(_build_snapshot_display(snap))

    @metrics_app.command("live")
    def metrics_live(
        interval: float = typer.Option(
            2.0, "--interval", "-i",
            help="Refresh interval in seconds.",
        ),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace name (default: registry default).",
        ),
    ) -> None:
        """Live-updating metrics dashboard. Press Ctrl+C to stop."""
        try:
            base_url = _api_url(workspace, "/metrics")
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        interval = max(interval, 1.0)

        console.print(f"[bold cyan]hirocli metrics live[/bold cyan]  (refresh every {interval:.1f}s, Ctrl+C to stop)\n")

        def _make_display() -> Table | Text:
            try:
                snap = _get_json(base_url)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return Text("Metrics collection is disabled.", style="yellow")
                if exc.code == 503:
                    return Text("Waiting for first sample...", style="dim")
                return Text(f"Server error: {exc}", style="red")
            except Exception as exc:
                return Text(f"Cannot reach server: {exc}", style="red")

            ts = snap.get("timestamp", 0)
            age = time.time() - ts if ts else 0
            header = Text(f"  Last sample: {age:.1f}s ago", style="dim")

            outer = Table(show_header=False, box=None, padding=(0, 0))
            outer.add_row(header)
            outer.add_row(_build_snapshot_display(snap))
            return outer

        try:
            with Live(_make_display(), console=console, refresh_per_second=1) as live:
                while True:
                    time.sleep(interval)
                    live.update(_make_display())
        except KeyboardInterrupt:
            console.print("\n[dim]Stopped.[/dim]")
