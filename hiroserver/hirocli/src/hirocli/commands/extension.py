"""Extension subcommands — thin CLI layer over the extension tools.

Extensions are programs that run on their own (HomeHiro first) and sign in on the
workspace's extension socket. Pair one with ``hiro extension add``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import typer
from hiro_commons.log import Logger
from hiro_commons.timestamps import human_datetime
from rich.console import Console
from rich.table import Table

from ..domain.workspace import WorkspaceError

# Tool imports happen inside each command body to keep ``commands/app.py``
# import cheap on fast paths like ``hiro start``.

log = Logger.get("CLI.EXTENSION")

_WORKSPACE_HELP = "Workspace name (default: registry default)."


def _human(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return human_datetime(datetime.fromisoformat(iso.replace("Z", "+00:00")))
    except ValueError:
        return iso


def register(extension_app: typer.Typer, console: Console) -> None:
    """Register extension commands."""

    @extension_app.command("add")
    def extension_add(
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
        ttl_seconds: Optional[int] = typer.Option(
            None, "--ttl-seconds", help="Pairing code lifetime in seconds (default from config)."
        ),
    ) -> None:
        """Make a pairing code to connect an extension (such as HomeHiro)."""
        from ..tools.extension import ExtensionAddTool

        log.info("hiro extension add", ttl_seconds=ttl_seconds)
        try:
            result = ExtensionAddTool().execute(workspace=workspace, ttl_seconds=ttl_seconds)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        console.print("[bold cyan]Pairing code created[/bold cyan]")
        console.print(f"  address : [bold]{result.address}[/bold]")
        console.print(f"  code    : [bold]{result.code}[/bold]")
        console.print(f"  expires : [bold]{_human(result.expires_at)}[/bold]")
        console.print("Type both into the extension's settings (HomeHiro: Settings, HiroLeague).")

    @extension_app.command("list")
    def extension_list(
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """List paired extensions."""
        from ..tools.extension import ExtensionListTool

        try:
            result = ExtensionListTool().execute(workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if not result.extensions:
            console.print("[dim]No paired extensions yet. Pair one with `hiro extension add`.[/dim]")
            return
        table = Table(title="Paired extensions", show_header=True)
        table.add_column("Name", style="bold")
        table.add_column("Version")
        table.add_column("Extension ID")
        table.add_column("Paired")
        table.add_column("Last seen")
        for ext in result.extensions:
            table.add_row(
                ext["name"] or "—",
                ext["version"] or "—",
                ext["extension_id"],
                _human(ext["paired_at"]),
                _human(ext["last_seen"]),
            )
        console.print(table)

    @extension_app.command("remove")
    def extension_remove(
        extension_id: str = typer.Argument(..., help="Extension ID to remove (see `hiro extension list`)."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Remove a paired extension; it is refused until paired again."""
        from ..tools.extension import ExtensionRemoveTool

        log.info("hiro extension remove", extension_id=extension_id)
        try:
            result = ExtensionRemoveTool().execute(extension_id=extension_id, workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        if result.removed:
            console.print(f"[green]Removed extension[/green] [bold]{result.extension_id}[/bold].")
            console.print("[dim]If it is connected now, it is refused from its next connection.[/dim]")
        else:
            console.print(f"[yellow]Extension not found:[/yellow] {result.extension_id}")

    @extension_app.command("address")
    def extension_address(
        host: Optional[str] = typer.Argument(
            None,
            help="Address to listen on: 127.0.0.1 (this machine), the Docker bridge, or the LAN address. "
            "Omit to show it.",
        ),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Show or set the address extensions connect on."""
        from ..tools.extension import ExtensionAddressTool

        log.info("hiro extension address", host=host)
        try:
            result = ExtensionAddressTool().execute(host=host, workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        console.print(f"  listens on : [bold]{result.host}:{result.port}[/bold]")
        console.print(f"  address    : [bold]{result.address}[/bold]")
        if result.note:
            console.print(f"[yellow]{result.note}[/yellow]")
        if result.restart_required:
            console.print("[cyan]Restart the server for the new address to take effect.[/cyan]")

    @extension_app.command("names")
    def extension_names(
        ip: Optional[str] = typer.Option(None, "--ip", help="LAN address apps' names point at ('' = names off)."),
        caddy_file: Optional[str] = typer.Option(None, "--caddy-file", help="File the core writes for Caddy."),
        caddy_main: Optional[str] = typer.Option(None, "--caddy-main", help="The hand-written Caddyfile."),
        caddy_reload: Optional[str] = typer.Option(None, "--caddy-reload", help="Command that reloads Caddy."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Show or set how apps' LAN names are set up on this machine, and the names apps claimed."""
        from ..tools.extension import ExtensionNamesTool

        log.info("hiro extension names", ip=ip, caddy_file=caddy_file)
        try:
            result = ExtensionNamesTool().execute(
                ip=ip, caddy_file=caddy_file, caddy_main=caddy_main, caddy_reload=caddy_reload, workspace=workspace
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        console.print(f"  names point at : [bold]{result.ip or '(off)'}[/bold]")
        console.print(f"  Caddy file     : {result.caddy_file or '(none)'}")
        console.print(f"  hand-written   : {result.caddy_main or '(none)'}")
        console.print(f"  reload Caddy   : {' '.join(result.caddy_reload) or '(none)'}")
        for n in result.names:
            console.print(f"  [green]{n['name']}[/green] → 127.0.0.1:{n['port']}  [dim]{n['extension_id']}[/dim]")
        if not result.names:
            console.print("  [dim]No app has claimed a name yet.[/dim]")
        if result.restart_required:
            console.print("[cyan]Restart the server for the change to take effect.[/cyan]")
