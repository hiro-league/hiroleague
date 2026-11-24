"""Device pairing/approval subcommands — thin CLI layer over device tools."""

from __future__ import annotations

from typing import Optional

import typer
from hiro_commons.log import Logger
from rich.console import Console
from rich.table import Table

from ..domain.workspace import WorkspaceError

# Tool imports happen inside each command body to keep ``commands/app.py``
# import cheap on fast paths like ``hiro start``.

log = Logger.get("CLI.DEVICE")

def register(device_app: typer.Typer, console: Console) -> None:
    """Register device management commands."""

    @device_app.command("add")
    def device_add(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
        ttl_seconds: Optional[int] = typer.Option(
            None, "--ttl-seconds",
            help="Pairing code lifetime in seconds (default from config).",
        ),
        code_length: Optional[int] = typer.Option(
            None, "--code-length",
            help="Pairing code length in digits (default from config).",
        ),
        person: Optional[str] = typer.Option(
            None, "--person", help="Whose the device will be: a person's id (default: the owner).",
        ),
    ) -> None:
        """Generate a short-lived pairing code for onboarding a device: it will be the person's."""
        from ..tools.device import DeviceAddTool

        log.info("hiro device add", ttl_seconds=ttl_seconds, code_length=code_length)

        try:
            result = DeviceAddTool().execute(
                workspace=workspace,
                ttl_seconds=ttl_seconds,
                code_length=code_length,
                person_id=person,
            )
        except (WorkspaceError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc

        from ..qr_rendering import render_qr_terminal

        render_qr_terminal(result.qr_payload)
        console.print("[bold cyan]Pairing code created[/bold cyan]")
        console.print(f"  gateway   : [bold]{result.gateway_url}[/bold]")
        console.print(f"  code      : [bold]{result.code}[/bold]")
        console.print(f"  expires_at: [bold]{result.expires_at}[/bold]")
        console.print("Scan the QR code or enter the details manually in the mobile app.")

    @device_app.command("list")
    def device_list(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
    ) -> None:
        """List approved paired devices."""
        from ..tools.device import DeviceListTool

        try:
            result = DeviceListTool().execute(workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc

        if not result.devices:
            console.print("[dim]No approved devices yet.[/dim]")
            return

        table = Table(title="Approved devices", show_header=True)
        table.add_column("Name", style="bold")
        table.add_column("Device ID")
        table.add_column("Person")
        table.add_column("Paired At")
        table.add_column("Expires At")

        for device in result.devices:
            table.add_row(
                device.get("device_name") or "—",
                device["device_id"],
                device.get("person_id") or "—",
                device["paired_at"],
                device["expires_at"] or "—",
            )
        console.print(table)

    @device_app.command("assign")
    def device_assign(
        device_id: str = typer.Argument(..., help="Approved device_id"),
        person: str = typer.Argument(..., help="The person's id it belongs to"),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
    ) -> None:
        """Say whose a paired device is: it then shows and writes only that person's conversations."""
        from ..tools.device import DeviceAssignTool

        log.info("hiro device assign", device_id=device_id, person_id=person)
        try:
            result = DeviceAssignTool().execute(device_id=device_id, person_id=person, workspace=workspace)
        except (WorkspaceError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        console.print(f"[green]{result.device_id}[/green] is now [bold]{result.person_name}[/bold]'s device.")

    @device_app.command("revoke")
    def device_revoke(
        device_id: str = typer.Argument(..., help="Approved device_id to revoke"),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
    ) -> None:
        """Revoke a previously approved paired device."""
        from ..tools.device import DeviceRevokeTool

        log.info("hiro device revoke", device_id=device_id)

        try:
            result = DeviceRevokeTool().execute(device_id=device_id, workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc

        if result.removed:
            console.print(f"[green]Revoked device[/green] [bold]{result.device_id}[/bold].")
        else:
            console.print(f"[yellow]Device not found:[/yellow] {result.device_id}")
