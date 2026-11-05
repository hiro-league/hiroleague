"""`hiro service` — run the Hiro server as a Linux systemd service (install, uninstall, status)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import typer
from hiro_commons.log import Logger
from hiro_commons.systemd_service import NeedsRootError, ServiceError
from hiro_commons.timestamps import human_datetime
from rich.console import Console

from ..domain.workspace import WorkspaceRegistry, admin_port_for

log = Logger.get("CLI.SERVICE")


def _first_admin_port() -> int:
    # The first workspace's admin port (slot 0); only used in the "next steps" hint, since the
    # service user's own workspace registry may not be readable from here.
    return admin_port_for(WorkspaceRegistry(), 0)


def _print_needs_root(console: Console, exc: NeedsRootError) -> None:
    console.print(f"[yellow]{exc.action} needs root.[/yellow]")
    console.print(
        "It writes the service definition to /etc/systemd/system and its secrets file to /etc/hiro, "
        "then asks systemd to load it. Run:"
    )
    console.print(f"  [bold cyan]{exc.command}[/bold cyan]")


def register(service_app: typer.Typer, console: Console) -> None:
    """Register `hiro service` subcommands."""

    @service_app.command("install")
    def install(
        user: Optional[str] = typer.Option(
            None, "--user", "-u",
            help="User the service runs as: your own user, or a dedicated one such as 'hiro'. "
                 "Default: the user running the install.",
        ),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace to run (default: the service user's default workspace, created on first start).",
        ),
    ) -> None:
        """Install the Hiro server as a systemd service: starts at boot, restarts on failure (Linux, root)."""
        log.info("hiro service install", user=user, workspace=workspace)
        from ..tools.service import ServiceInstallTool

        try:
            result = ServiceInstallTool().execute(user=user, workspace=workspace)
        except NeedsRootError as exc:
            _print_needs_root(console, exc)
            raise typer.Exit(1)
        except ServiceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        console.print(
            f"[green]✅ HiroLeague service installed and started:[/green] [bold]{result.service}[/bold] "
            f"(runs as [bold]{result.user}[/bold], starts at boot, restarts if it fails)."
        )
        console.print(f"  Runs:    {result.exec_start}")
        console.print(f"  Unit:    {result.unit_path}")
        if result.env_file_created:
            console.print(f"  Secrets: {result.env_file} [dim](new; only {result.user} and root can read it)[/dim]")
        else:
            console.print(f"  Secrets: {result.env_file} [dim](kept as it was)[/dim]")
        port = _first_admin_port()
        console.print("\n[bold]Next steps[/bold]")
        console.print(f"  1. Add your provider API keys:  [cyan]sudoedit {result.env_file}[/cyan]  (e.g. OPENAI_API_KEY=...)")
        console.print(f"  2. Load them:                   [cyan]sudo systemctl restart {result.service}[/cyan]")
        console.print(
            f"  3. Open the admin UI. It listens on this machine only (port {port} for the first workspace); "
            f"from another computer: [cyan]ssh -L {port}:localhost:{port} <this-server>[/cyan], "
            f"then http://localhost:{port}"
        )
        console.print(
            "     In Providers/Models → Providers, click [bold]Scan environment[/bold] once to turn on the providers "
            "whose keys you added."
        )
        console.print(
            f"\n  State: [cyan]hiro service status[/cyan] · Logs: [cyan]journalctl -u {result.service} -f[/cyan]"
        )

    @service_app.command("uninstall")
    def uninstall(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace whose service to remove (default: the default service).",
        ),
    ) -> None:
        """Stop and remove the systemd service. Keeps the workspace and the secrets file (Linux, root)."""
        log.info("hiro service uninstall", workspace=workspace)
        from ..tools.service import ServiceUninstallTool

        try:
            result = ServiceUninstallTool().execute(workspace=workspace)
        except NeedsRootError as exc:
            _print_needs_root(console, exc)
            raise typer.Exit(1)
        except ServiceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if result.removed:
            console.print(f"[green]Service removed:[/green] {result.service} is stopped and no longer starts at boot.")
        else:
            console.print(f"[yellow]{result.service} is not installed; nothing to remove.[/yellow]")
        console.print("[dim]Your workspace (data, settings) was not touched.[/dim]")
        if result.env_file:
            console.print(
                f"The secrets file was kept: {result.env_file}. Delete it if you no longer need it: "
                f"[cyan]sudo rm {result.env_file}[/cyan]"
            )

    @service_app.command("status")
    def status(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace whose service to show (default: the default service).",
        ),
    ) -> None:
        """Show whether the systemd service is installed, running, and enabled at boot (Linux)."""
        from ..tools.service import ServiceStatusTool

        try:
            result = ServiceStatusTool().execute(workspace=workspace)
        except ServiceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if not result.installed:
            exe = result.hiro_executable or "hiro"
            console.print(f"[yellow]{result.service} is not installed.[/yellow] Install it with:")
            console.print(f"  [cyan]sudo {exe} service install[/cyan]")
            raise typer.Exit(1)

        colour = {"active": "green", "failed": "red"}.get(result.active_state, "yellow")
        state = f"[{colour}]{result.active_state}[/{colour}]"
        if result.sub_state:
            state += f" ({result.sub_state})"
        if result.active_since_iso and result.active_state == "active":
            state += f" since {human_datetime(datetime.fromisoformat(result.active_since_iso))}"
        console.print(f"[bold]{result.service}[/bold]: {state}")
        if result.main_pid:
            console.print(f"  PID:      {result.main_pid}")
        console.print(f"  Runs as:  {result.user or '[red]root (not supported)[/red]'}")
        boot = "yes" if result.enabled_state == "enabled" else f"no ({result.enabled_state or 'unknown'})"
        console.print(f"  At boot:  {boot}")
        if result.restarts is not None:
            console.print(f"  Restarts: {result.restarts} since it was last started by hand")
        if result.unit_path:
            console.print(f"  Unit:     {result.unit_path}")
        console.print(f"  Secrets:  {result.env_file or '[red]missing: the service cannot start without it[/red]'}")
        console.print(f"  Logs:     [cyan]journalctl -u {result.service} -f[/cyan]")
        if result.active_state != "active":
            raise typer.Exit(3)  # like `systemctl status`: non-zero when not running
