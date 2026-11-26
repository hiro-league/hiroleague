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
    from . import extension_install

    extension_install.register(extension_app, console)

    def _remove_installed(name: str, *, purge: bool, yes: bool, workspace: str | None) -> bool:
        """Remove an app the core installed (by its key, or its paired record's id); False when it isn't one."""
        import sys
        from pathlib import Path

        import httpx

        from ..domain import installs
        from ..domain.extensions import get_paired_extension
        from ..domain.hiro_home import app_folder
        from ..domain.workspace import resolve_workspace

        try:
            entry, _ = resolve_workspace(workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        workspace_path = Path(entry.path)
        row = installs.get_install(workspace_path, name)
        if row is None:
            found = get_paired_extension(workspace_path, name)
            row = installs.get_install(workspace_path, found.name) if found is not None else None
        if row is None:
            return False
        log.info("hiro extension remove: installed", key=row.key, purge=purge)
        if purge and not yes:
            if not sys.stdin.isatty():
                console.print("[red]--purge deletes the app's data: pass --yes too, or run it in a terminal.[/red]")
                raise typer.Exit(1)
            folder = app_folder(row.key, Path(row.home)).root
            if not typer.confirm(f"Delete {row.title}'s folder and data too ({folder})? It can't be undone.",
                                 default=False):
                console.print("Nothing was changed.")
                raise typer.Exit(1)
        try:
            extension_install.remove_installed(console, workspace_path, entry.id, row.key, purge=purge)
        except (extension_install._Stop, RuntimeError, OSError, httpx.HTTPError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        return True

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
            raise typer.Exit(1) from exc

        console.print("[bold cyan]Pairing code created[/bold cyan]")
        console.print(f"  address : [bold]{result.address}[/bold]")
        console.print(f"  code    : [bold]{result.code}[/bold]")
        console.print(f"  expires : [bold]{_human(result.expires_at)}[/bold]")
        console.print("Type both into the extension's settings (HomeHiro: Settings, HiroLeague).")

    @extension_app.command("pair-again")
    def extension_pair_again(
        extension_id: str = typer.Argument(..., help="The app's extension ID (see `hiro extension list`)."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """A pairing code for one paired app that lost its key: it pairs again and keeps its rights, AI picks and
        LAN name."""
        from ..tools.extension import ExtensionPairAgainTool

        log.info("hiro extension pair-again", extension_id=extension_id)
        try:
            result = ExtensionPairAgainTool().execute(extension_id=extension_id, workspace=workspace)
        except (WorkspaceError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc

        console.print(f"[bold cyan]Pairing code to pair {result.pairs_again} again[/bold cyan]")
        console.print(f"  address : [bold]{result.address}[/bold]")
        console.print(f"  code    : [bold]{result.code}[/bold]")
        console.print(f"  expires : [bold]{_human(result.expires_at)}[/bold]")
        console.print(f"Type both into {result.pairs_again}'s settings. It keeps its rights, AI picks and name.")

    @extension_app.command("list")
    def extension_list(
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
        as_json: bool = typer.Option(False, "--json", help="Print the extensions and the installs as JSON."),
    ) -> None:
        """List every extension: its channel plugins and its apps, and the apps the core installed."""
        import json

        from ..tools.extension import ExtensionListTool
        from ..tools.extension_install import ExtensionInstallsTool

        try:
            result = ExtensionListTool().execute(workspace=workspace)
            installed = ExtensionInstallsTool().execute(workspace=workspace).installs
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc

        if as_json:
            print(json.dumps({"extensions": result.extensions, "installs": installed}, indent=2))
            return
        if installed:
            table = Table(title="Installed by the core", show_header=True)
            for column in ("Key", "Version", "Port", "State", "Running", "Data"):
                table.add_column(column, style="bold" if column == "Key" else None)
            for row in installed:
                running = {True: "yes", False: "no", None: "—"}[row["running"]]
                state = row["state"] + (f": {row['step']}" if row["state"] == "failed" else "")
                table.add_row(row["key"], row["version"], str(row["port"] or "—"), state, running, row["data"])
            console.print(table)
        if not result.extensions:
            console.print("[dim]No extensions yet. Pair an app with `hiro extension add`.[/dim]")
            return
        table = Table(title="Extensions", show_header=True)
        table.add_column("Name", style="bold")
        table.add_column("Kind")
        table.add_column("Version")
        table.add_column("Extension ID")
        table.add_column("Paired")
        table.add_column("Last seen")
        for ext in result.extensions:
            table.add_row(
                ext["name"] or "—",
                ext["kind"],
                ext["version"] or "—",
                ext["extension_id"],
                _human(ext["paired_at"]),
                _human(ext["last_seen"]),
            )
        console.print(table)

    @extension_app.command("remove")
    def extension_remove(
        extension_id: str = typer.Argument(
            ..., help="Extension ID to remove, or an installed app's key (see `hiro extension list`)."
        ),
        purge: bool = typer.Option(False, "--purge", help="An installed app: its folder and its data go too."),
        yes: bool = typer.Option(False, "--yes", help="With --purge: don't ask before deleting its data."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Remove a paired extension; it is refused until paired again. An app's LAN name, its rights and its AI picks
        go with it; its own data stays. An app the core installed loses its service and account too (one
        administrator step), and with --purge its folder and data."""
        if _remove_installed(extension_id, purge=purge, yes=yes, workspace=workspace):
            return
        if purge:
            console.print("[red]--purge is for an app the core installed: this one keeps its own data.[/red]")
            raise typer.Exit(1)
        from pathlib import Path

        import httpx
        from hiro_commons.process import is_running, read_pid

        from ..constants import PID_FILENAME
        from ..domain.extensions import KIND_APP, get_paired_extension
        from ..domain.workspace import resolve_workspace
        from ..domain.workspace_server_client import post_invoke_sync
        from ..tools.extension import ExtensionRemoveResult, ExtensionRemoveTool

        log.info("hiro extension remove", extension_id=extension_id)
        try:
            entry, _ = resolve_workspace(workspace)
            workspace_path = Path(entry.path)
            found = get_paired_extension(workspace_path, extension_id)
            live = is_running(read_pid(workspace_path, PID_FILENAME))
            if live and found is not None and found.kind == KIND_APP:
                # The running core keeps preferences in memory and announces the names: it removes an app, or it
                # would write the app's picks back and keep its name live. A channel touches neither: removed here.
                out = post_invoke_sync(workspace_path, "extension_remove",
                                       {"extension_id": extension_id, "workspace": entry.id})
                result = ExtensionRemoveResult(**out)
            else:
                result = ExtensionRemoveTool().execute(extension_id=extension_id, workspace=workspace)
        except (WorkspaceError, RuntimeError, OSError, ValueError, httpx.HTTPError) as exc:
            # The workspace unknown, the server not answering, or the tool's refusal (the mandatory channel).
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        if not result.removed:
            console.print(f"[yellow]Extension not found:[/yellow] {result.extension_id}")
            return
        console.print(f"[green]Removed extension[/green] [bold]{result.name or result.extension_id}[/bold].")
        if result.site_name:
            console.print(f"Its name {result.site_name} is free again.")
        if result.rights_dropped or result.picks_dropped:
            console.print(f"Its rights in {len(result.rights_dropped)} role(s) and {len(result.picks_dropped)} AI or "
                          "voice pick(s) went with it.")
        if result.kind != KIND_APP:
            return
        if live:
            console.print("[dim]It is refused from its next connection; its own data stays where it is.[/dim]")
        else:
            console.print("[dim]Its own data stays where it is. The front door forgets its name at the core's next "
                          "start.[/dim]")

    @extension_app.command("approve")
    def extension_approve(
        extension: str = typer.Argument(..., help="The app's name or id (see `hiro extension list`)."),
        optional: Optional[list[str]] = typer.Option(
            None, "--optional", help="An optional item to approve too (permission, or permission:subject); repeat it."
        ),
        all_: bool = typer.Option(False, "--all", help="Approve every optional item too."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Approve what a paired app asks to do on its own (Permissions phase 8): every required item, and the
        optional ones named. In the running core its LAN name is claimed and the app is told at once."""
        from pathlib import Path

        import httpx
        from hiro_commons.process import is_running, read_pid

        from ..constants import PID_FILENAME
        from ..domain.workspace import resolve_workspace
        from ..domain.workspace_server_client import post_invoke_sync
        from ..tools.extension import ExtensionApprovalResult, ExtensionApproveTool

        log.info("hiro extension approve", extension=extension, all=all_)
        params = {"extension": extension, "optional": optional or [], "all": all_}
        try:
            entry, _ = resolve_workspace(workspace)
            workspace_path = Path(entry.path)
            if is_running(read_pid(workspace_path, PID_FILENAME)):
                result = ExtensionApprovalResult(**post_invoke_sync(workspace_path, "extension_approve",
                                                                    {**params, "workspace": entry.id}))
            else:
                result = ExtensionApproveTool().execute(**params, workspace=workspace)
        except (WorkspaceError, RuntimeError, OSError, ValueError, LookupError, httpx.HTTPError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        approved = [i for i in result.items if i["approved"]]
        console.print(f"[green]Approved[/green] [bold]{result.name}[/bold]: {len(approved)} item(s).")
        for item in result.items:
            mark = "[green]yes[/green]" if item["approved"] else "[yellow]no[/yellow]"
            subject = f" ({item['subject']})" if item["subject"] else ""
            console.print(f"  {mark}  {item['words']}{subject}")

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
            raise typer.Exit(1) from exc
        console.print(f"  listens on : [bold]{result.host}:{result.port}[/bold]")
        console.print(f"  address    : [bold]{result.address}[/bold]")
        if result.note:
            console.print(f"[yellow]{result.note}[/yellow]")
        if result.restart_required:
            console.print("[cyan]Restart the server for the new address to take effect.[/cyan]")

    @extension_app.command("names")
    def extension_names(
        ip: Optional[str] = typer.Option(None, "--ip", help="LAN address the names point at ('' = names off)."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Show or set the LAN address this machine's names point at, and the names apps claimed (`hiro sites` lists
        every name served)."""
        from ..tools.extension import ExtensionNamesTool

        log.info("hiro extension names", ip=ip)
        try:
            result = ExtensionNamesTool().execute(ip=ip, workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        console.print(f"  names point at : [bold]{result.ip or '(off)'}[/bold]")
        for n in result.names:
            extra = "  [dim](extra)[/dim]" if n["extra"] else ""
            console.print(f"  [green]{n['name']}[/green] → 127.0.0.1:{n['port']}  [dim]{n['extension_id']}[/dim]{extra}")
        if not result.names:
            console.print("  [dim]No app has claimed a name yet.[/dim]")
        if result.restart_required:
            console.print("[cyan]Restart the server for the change to take effect.[/cyan]")
