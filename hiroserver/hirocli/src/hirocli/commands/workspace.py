"""Workspace management subcommands — thin CLI layer over workspace tools.

hiro workspace list
hiro workspace create <name> [--path P] [--set-default]
hiro workspace setup [<name-or-id>]
hiro workspace remove <name-or-id> [--purge] [--yes]
hiro workspace update <name-or-id> [--name N] [--set-default] [--gateway-url URL]
hiro workspace show [<name-or-id>]
hiro workspace teardown [<name-or-id>] [--purge]
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from hiro_commons.process import is_running, read_pid
from rich.console import Console
from rich.table import Table

from hiro_commons.log import Logger

from ..constants import PID_FILENAME
from ..domain.workspace import WorkspaceError, resolve_workspace
from ..tools.server import SetupTool, TeardownTool
from ..tools.workspace import (
    WorkspaceCreateTool,
    WorkspaceListTool,
    WorkspaceRemoveTool,
    WorkspaceShowTool,
    WorkspaceUpdateTool,
)

log = Logger.get("CLI.WORKSPACE")

def register(workspace_app: typer.Typer, console: Console) -> None:
    """Register workspace management commands."""

    @workspace_app.command("list")
    def workspace_list() -> None:
        """List all configured workspaces."""
        result = WorkspaceListTool().execute()

        if not result.workspaces:
            console.print(
                "[dim]No workspaces configured. "
                "Run [bold]hiro workspace create <name>[/bold] to get started.[/dim]"
            )
            return

        table = Table(title="Workspaces", show_header=True)
        table.add_column("", width=2, no_wrap=True)
        table.add_column("Name", style="bold")
        table.add_column("ID", style="dim")
        table.add_column("Setup")
        table.add_column("Server")
        table.add_column("Autostart")
        table.add_column("HTTP")
        table.add_column("Admin")
        table.add_column("Gateway URL")
        table.add_column("Path")

        for ws in result.workspaces:
            workspace_path = Path(ws["path"])
            pid = read_pid(workspace_path, PID_FILENAME)
            running = is_running(pid)

            default_marker = "[cyan]*[/cyan]" if ws["is_default"] else ""
            setup_str = "[green]configured[/green]" if ws["is_configured"] else "[yellow]needs setup[/yellow]"
            server_str = "[green]running[/green]" if running else "[dim]stopped[/dim]"
            method = ws.get("autostart_method")
            autostart_str = {
                "elevated": "[magenta]elevated[/magenta]",
                "schtasks": "[blue]schtasks[/blue]",
                "registry": "[cyan]registry[/cyan]",
                "skipped": "[dim]skipped[/dim]",
                "failed": "[red]failed[/red]",
            }.get(method or "", "[dim]—[/dim]")
            http_str = f":{ws['http_port']}"
            admin_str = f":{ws['admin_port']}"
            gw_str = ws.get("gateway_url") or "[dim]—[/dim]"
            short_id = ws["id"][:8]
            table.add_row(
                default_marker, ws["name"], short_id, setup_str, server_str,
                autostart_str, http_str, admin_str, gw_str, ws["path"],
            )

        console.print(table)
        console.print("\n[cyan]*[/cyan] = default workspace")

    @workspace_app.command("create")
    def workspace_create(
        name: str = typer.Argument(..., help="Workspace name (e.g. 'default', 'work')"),
        path: Optional[str] = typer.Option(
            None, "--path", "-p",
            help="Custom folder path. Defaults to the platform data dir.",
        ),
        make_default: bool = typer.Option(
            False, "--set-default",
            help="Set this workspace as the default after creation.",
        ),
    ) -> None:
        """Create a new workspace."""
        try:
            result = WorkspaceCreateTool().execute(
                name=name,
                path=path,
                set_default=make_default,
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        # workspace create makes the workspace — open sinks after so the path exists.
        Logger.open_log_dir(Path(result.path) / "logs")
        log.info("hiro workspace create", name=result.name, path=result.path, set_default=make_default)

        console.print(f"[green]Workspace '[bold]{result.name}[/bold]' created.[/green]")
        console.print(f"  id          : [dim]{result.id}[/dim]")
        console.print(f"  path        : [bold]{result.path}[/bold]")
        console.print(f"  http_port   : [bold]{result.http_port}[/bold]")
        console.print(f"  plugin_port : [bold]{result.plugin_port}[/bold]")
        console.print(f"  admin_port  : [bold]{result.admin_port}[/bold]")

        if result.is_default:
            console.print("  [cyan]Set as default workspace.[/cyan]")

        console.print(f"\nNext: [bold]hiro workspace setup {result.name}[/bold]")

    @workspace_app.command("setup")
    def workspace_setup(
        workspace: Optional[str] = typer.Argument(
            None,
            help="Workspace name or id to configure. Omit to use the registry default.",
        ),
        gateway_url: Optional[str] = typer.Option(
            None, "--gateway-url", "-g",
            help="WebSocket gateway URL (e.g. ws://myhost:8765)",
        ),
        http_port: Optional[int] = typer.Option(
            None, "--port", "-p", help="Local HTTP server port (default: from workspace slot)"
        ),
        skip_autostart: bool = typer.Option(
            False, "--skip-autostart", help="Do not register auto-start"
        ),
        start_server: bool = typer.Option(
            False, "--start-server",
            help="Start the server immediately after setup completes.",
        ),
        elevated_task: bool = typer.Option(
            False, "--elevated-task",
            help="(Windows) Request UAC elevation to create a high-privilege Task Scheduler entry.",
        ),
        metrics: Optional[bool] = typer.Option(
            None, "--metrics/--no-metrics",
            help="Enable or disable system metrics collection (persisted to config).",
        ),
        metrics_interval: Optional[float] = typer.Option(
            None, "--metrics-interval",
            help="Metrics sampling interval in seconds (min 1.0, persisted to config).",
        ),
        non_interactive: bool = typer.Option(
            False,
            "--non-interactive",
            help="Skip interactive API key provisioning; auto-import env keys in the tool when possible.",
        ),
    ) -> None:
        """Configure gateway, generate device ID, and register auto-start."""
        console.print("[bold cyan]hiro workspace setup[/bold cyan]")

        from ..domain.config import load_config as _load_config

        try:
            entry, _ = resolve_workspace(workspace)
            existing = _load_config(Path(entry.path))
            default_gw = existing.gateway_url
        except (WorkspaceError, Exception):
            default_gw = "ws://localhost:8765"

        effective_gateway_url = gateway_url
        if effective_gateway_url is None:
            if non_interactive:
                effective_gateway_url = default_gw
            else:
                effective_gateway_url = typer.prompt(
                    "Gateway WebSocket URL",
                    default=default_gw,
                )

        use_interactive_credentials = sys.stdin.isatty() and not non_interactive
        try:
            result = SetupTool().execute(
                gateway_url=effective_gateway_url,
                workspace=workspace,
                http_port=http_port,
                skip_autostart=skip_autostart,
                start_server=start_server,
                elevated_task=elevated_task,
                metrics_enabled=metrics,
                metrics_interval=metrics_interval,
                skip_env_import=use_interactive_credentials,
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        try:
            from ..domain.config import load_config, resolve_log_dir

            ws_path = Path(result.workspace_path)
            cfg = load_config(ws_path)
            Logger.open_log_dir(resolve_log_dir(ws_path, cfg))
        except Exception:
            pass
        log.info(
            "hiro workspace setup",
            workspace=result.workspace,
            gateway_url=result.gateway_url,
            http_port=result.http_port,
            skip_autostart=skip_autostart,
            elevated_task=elevated_task,
            start_server=start_server,
            device_id=result.device_id,
            autostart=result.autostart_method,
        )

        console.print(f"[green]Config saved to[/green] {result.workspace_path}/config.json")
        console.print(f"  workspace  : [bold]{result.workspace}[/bold]")
        console.print(f"  device_id  : [bold]{result.device_id}[/bold]")
        console.print(f"  gateway_url: [bold]{result.gateway_url}[/bold]")
        console.print(f"  http_port  : [bold]{result.http_port}[/bold]")
        console.print(f"  master_key : [bold]{result.master_key}[/bold]")
        console.print(f"  desktop_pub: [bold]{result.desktop_pub}[/bold]")
        console.print("  channel    : [bold]devices[/bold] (mandatory)")

        if result.autostart_registered:
            method = result.autostart_method
            if method == "elevated":
                console.print(
                    "[green]Auto-start registered[/green] via Task Scheduler "
                    "(elevated, run-level: HIGHEST)."
                )
            elif method == "schtasks":
                console.print(
                    "[green]Auto-start registered[/green] via Task Scheduler "
                    "(run-level: LIMITED, no elevation needed)."
                )
            elif method == "registry":
                console.print(
                    "[green]Auto-start registered[/green] via Registry Run key "
                    "[dim](Task Scheduler was unavailable â€” registry fallback used)[/dim]."
                )
        elif result.autostart_method == "failed":
            console.print("[yellow]Auto-start registration failed.[/yellow]")

        if result.providers_imported:
            console.print(
                f"[green]Imported[/green] {result.providers_imported} provider credential(s) "
                "from environment into the workspace store."
            )
        elif use_interactive_credentials:
            console.print(
                "[dim]Automatic environment key import was skipped for this run; "
                "use the prompts below or `hiro provider add` later.[/dim]"
            )

        if use_interactive_credentials:
            from .provider import interactive_credential_provisioning

            interactive_credential_provisioning(
                Path(result.workspace_path),
                result.workspace_id,
                result.workspace,
                console,
            )

        if result.server_started:
            console.print("\n[green]Server started.[/green]")
        else:
            console.print(
                f"\nRun [bold]hiro start --workspace {result.workspace}[/bold] to start the server."
            )

    @workspace_app.command("remove")
    def workspace_remove(
        workspace: str = typer.Argument(..., help="Workspace name or id to remove"),
        purge: bool = typer.Option(
            False, "--purge",
            help="Also delete the workspace folder from disk.",
        ),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    ) -> None:
        """Remove a workspace from the registry."""
        if not yes:
            action = "remove and DELETE the folder of" if purge else "remove"
            typer.confirm(
                f"Are you sure you want to {action} workspace '{workspace}'?", abort=True
            )

        log.info("hiro workspace remove", workspace_arg=workspace, purge=purge)

        try:
            result = WorkspaceRemoveTool().execute(workspace=workspace, purge=purge)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        console.print(f"[green]Workspace '[bold]{result.name}[/bold]' removed.[/green]")
        if result.purged:
            console.print("  Workspace folder deleted from disk.")

    @workspace_app.command("update")
    def workspace_update(
        workspace: str = typer.Argument(..., help="Workspace name or id to update"),
        new_name: Optional[str] = typer.Option(
            None, "--name", "-n",
            help="New display name for the workspace.",
        ),
        make_default: bool = typer.Option(
            False, "--set-default",
            help="Set this workspace as the default.",
        ),
        gateway_url: Optional[str] = typer.Option(
            None, "--gateway-url", "-g",
            help="New gateway WebSocket URL (light update — no key regen). "
                 "For full reconfiguration use 'hiro workspace setup'.",
        ),
    ) -> None:
        """Update workspace name, default flag, and/or gateway URL."""
        if new_name is None and not make_default and gateway_url is None:
            console.print("[yellow]Nothing to update. Pass --name, --set-default, or --gateway-url.[/yellow]")
            raise typer.Exit(0)

        log.info("hiro workspace update", name=new_name, set_default=make_default, gateway_url=gateway_url)

        try:
            result = WorkspaceUpdateTool().execute(
                workspace=workspace,
                name=new_name,
                set_default=make_default,
                gateway_url=gateway_url,
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if result.renamed:
            console.print(f"  [green]Renamed[/green] → '[bold]{result.name}[/bold]'")
        if result.default_changed:
            console.print(f"  [green]Default workspace set to[/green] '[bold]{result.name}[/bold]'")
        if result.gateway_updated:
            console.print(f"  [green]Gateway URL updated.[/green]")
        if not any([result.renamed, result.default_changed, result.gateway_updated]):
            console.print("[dim]No changes made (values were already the same).[/dim]")

    @workspace_app.command("show")
    def workspace_show(
        workspace: Optional[str] = typer.Argument(
            None, help="Workspace name or id (omit to show the default)"
        ),
    ) -> None:
        """Show details of a workspace."""
        try:
            result = WorkspaceShowTool().execute(workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        workspace_path = Path(result.path)
        pid = read_pid(workspace_path, PID_FILENAME)
        running = is_running(pid)

        table = Table(
            title=f"Workspace: {result.name}",
            show_header=False,
            box=None,
            padding=(0, 2),
        )
        table.add_column("Key", style="bold")
        table.add_column("Value")

        table.add_row("Name", result.name)
        table.add_row("ID", f"[dim]{result.id}[/dim]")
        table.add_row("Path", result.path)
        table.add_row("Default", "[cyan]yes[/cyan]" if result.is_default else "no")
        table.add_row(
            "Setup",
            "[green]configured[/green]" if result.is_configured else "[yellow]needs setup[/yellow]",
        )
        table.add_row(
            "Server",
            f"[green]running[/green] (PID {pid})" if running else "[dim]stopped[/dim]",
        )
        if result.is_configured:
            ws_status = "[green]connected[/green]" if result.ws_connected else "[dim]disconnected[/dim]"
            if result.last_connected:
                ws_status += f" [dim](last: {result.last_connected})[/dim]"
            table.add_row("Gateway URL", result.gateway_url or "—")
            table.add_row("Gateway WS", ws_status)
            table.add_row("Device ID", result.device_id or "—")
            autostart_display = {
                "elevated": "[magenta]elevated[/magenta] (Task Scheduler, HIGHEST)",
                "schtasks": "[blue]schtasks[/blue] (Task Scheduler, LIMITED)",
                "registry": "[cyan]registry[/cyan] (HKCU Run key)",
                "skipped": "[dim]skipped[/dim]",
                "failed": "[red]failed[/red]",
            }.get(result.autostart_method or "", "[dim]—[/dim]")
            table.add_row("Autostart", autostart_display)
        table.add_row("HTTP port", str(result.http_port))
        table.add_row("Plugin port", str(result.plugin_port))
        table.add_row("Admin port", str(result.admin_port))
        table.add_row("Port slot", str(result.port_slot))

        console.print(table)

    @workspace_app.command("teardown")
    def workspace_teardown(
        workspace: Optional[str] = typer.Argument(
            None,
            help="Workspace name or id to tear down. Omit to use the registry default.",
        ),
        purge: bool = typer.Option(
            False, "--purge",
            help="Also delete the workspace folder (config, state, keys, logsâ€¦).",
        ),
    ) -> None:
        """Stop server and remove all auto-start registrations for a workspace."""
        console.print("[bold cyan]hiro workspace teardown[/bold cyan]")
        log.info("hiro workspace teardown", purge=purge)

        try:
            result = TeardownTool().execute(
                workspace=workspace,
                purge=purge,
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            return

        if result.autostart_removed:
            console.print("[green]Auto-start removed[/green] (Task Scheduler + Registry).")
        else:
            console.print("[yellow]Auto-start removal failed or skipped.[/yellow]")

        if purge:
            console.print(f"[green]Workspace folder removed:[/green] {result.workspace_path}")
            console.print(f"[green]Workspace '{result.workspace}' removed from registry.[/green]")

        console.print("\n[green]Teardown complete.[/green]")
