"""Root CLI command registrations."""

from __future__ import annotations

from typing import Optional

import typer
from hiro_commons.log import Logger
from rich.console import Console
from rich.table import Table

from ..domain.workspace import WorkspaceError
from ..tools.server import (
    RestartTool,
    StartTool,
    StatusTool,
    StopTool,
    UninstallTool,
)

log = Logger.get("CLI.SERVER")

def register(app: typer.Typer, console: Console) -> None:
    """Register root-level commands on the provided app."""

    @app.command()
    def start(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace to start (default: registry default).",
        ),
        foreground: bool = typer.Option(
            False, "--foreground", "-f",
            help=(
                "Run the server in the foreground with live log output. "
                "Press Ctrl+C to stop."
            ),
        ),
        admin: bool = typer.Option(
            False, "--admin",
            help="Also start the admin UI on its dedicated port (localhost only).",
        ),
        metrics: bool = typer.Option(
            False, "--metrics",
            help="Enable system metrics collection for this run (not persisted).",
        ),
    ) -> None:
        """Start the Hiro server (background by default, foreground with -f)."""
        log.info("hiro start", foreground=foreground, admin=admin, metrics=metrics)

        try:
            result = StartTool().execute(workspace=workspace, foreground=foreground, admin=admin, metrics=metrics)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if result.already_running:
            console.print(f"[yellow]Server already running (PID {result.pid}).[/yellow]")
        else:
            console.print(
                f"[green]Server started[/green] (PID {result.pid}). "
                f"HTTP: http://{result.http_host}:{result.http_port}/status"
            )
            if result.admin_port:
                console.print(
                    f"  Admin UI: [cyan]http://127.0.0.1:{result.admin_port}[/cyan]"
                )

    @app.command()
    def stop(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace to stop (default: registry default).",
        ),
    ) -> None:
        """Stop the running Hiro server."""
        log.info("hiro stop")

        try:
            result = StopTool().execute(workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if result.was_running:
            console.print(f"[green]Server stopped[/green] (was PID {result.pid}).")
        else:
            console.print("[yellow]Server is not running.[/yellow]")

    @app.command()
    def restart(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace to restart (default: registry default).",
        ),
        foreground: bool = typer.Option(
            False, "--foreground", "-f",
            help=(
                "Run the restarted server in the foreground with live log output. "
                "Press Ctrl+C to stop."
            ),
        ),
        admin: bool = typer.Option(
            False, "--admin",
            help="Also start the admin UI on its dedicated port (localhost only).",
        ),
        metrics: bool = typer.Option(
            False, "--metrics",
            help="Enable system metrics collection for this run (not persisted).",
        ),
    ) -> None:
        """Gracefully restart the Hiro server (stop + start)."""
        log.info("hiro restart", foreground=foreground, admin=admin, metrics=metrics)

        try:
            result = RestartTool().execute(
                workspace=workspace, foreground=foreground, admin=admin, metrics=metrics,
            )
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if result.was_running:
            console.print(
                f"[green]Server restarted[/green] "
                f"(was PID {result.pid}, now PID {result.new_pid})."
            )
        else:
            console.print(
                f"[green]Server started[/green] (was not running, PID {result.new_pid})."
            )
        console.print(
            f"  HTTP: http://{result.http_host}:{result.http_port}/status"
        )
        if result.admin_port:
            console.print(
                f"  Admin UI: [cyan]http://127.0.0.1:{result.admin_port}[/cyan]"
            )

    @app.command()
    def status(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace to query (omit to show all workspaces).",
        ),
    ) -> None:
        """Show server and WebSocket connection status."""
        try:
            result = StatusTool().execute(workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if not result.workspaces:
            console.print("[dim]No workspaces configured.[/dim]")
            return

        for ws in result.workspaces:
            _print_workspace_status_entry(console, ws)
            if len(result.workspaces) > 1:
                console.print()

    @app.command()
    def uninstall(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace to uninstall (default: registry default).",
        ),
        purge: bool = typer.Option(False, "--purge", help="Also delete the workspace folder."),
    ) -> None:
        """Stop server, remove auto-start, then print package uninstall commands."""
        console.print("[bold cyan]hiro uninstall[/bold cyan]")
        log.info("hiro uninstall", purge=purge)

        try:
            result = UninstallTool().execute(
                workspace=workspace,
                purge=purge,
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            return

        td = result.teardown
        if td.autostart_removed:
            console.print("[green]Auto-start removed[/green] (Task Scheduler + Registry).")
        else:
            console.print("[yellow]Auto-start removal failed or skipped.[/yellow]")

        if purge:
            console.print(f"[green]Workspace folder removed:[/green] {td.workspace_path}")
            console.print(f"[green]Workspace '{td.workspace}' removed from registry.[/green]")

        # End users install the `hiroleague` umbrella package; workspace devs
        # use `uv tool install --editable hirocli` directly. Show both flows so
        # the message works regardless of how the user installed it.
        console.print(
            "\n[bold]To fully remove Hiro League, run one of:[/bold]\n"
            "  [cyan]pip uninstall hiroleague[/cyan]                  (end user, pip install)\n"
            "  [cyan]uv tool uninstall hirocli[/cyan]                  (workspace dev, uv tool)\n"
            "  [cyan]uv tool uninstall hiro-channel-devices hirogate[/cyan]  (workspace dev, also remove plugin/gateway)\n"
        )


def _print_workspace_status_entry(
    console: Console,
    ws: object,
) -> None:
    from ..tools.server import WorkspaceStatusEntry
    assert isinstance(ws, WorkspaceStatusEntry)

    title = f"hiro status — {ws.name}"
    if ws.is_default:
        title += " [cyan](default)[/cyan]"

    table = Table(title=title, show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")

    table.add_row("ID", f"[dim]{ws.id}[/dim]")
    table.add_row("Server running", "[green]yes[/green]" if ws.server_running else "[red]no[/red]")
    table.add_row("PID", str(ws.pid) if ws.pid else "—")
    table.add_row(
        "WS connected",
        "[green]yes[/green]" if ws.ws_connected else "[red]no[/red]",
    )
    table.add_row("Last connected", ws.last_connected or "—")
    table.add_row("Gateway URL", ws.gateway_url or "—")
    table.add_row("Device ID", ws.device_id)
    table.add_row(
        "HTTP API",
        f"http://{ws.http_host}:{ws.http_port}/status" if ws.server_running else "—",
    )

    console.print(table)
