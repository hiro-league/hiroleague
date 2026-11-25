"""`hiro sites`: every name this machine serves, and the owner's own (extra names, other sites). Thin layer over
tools/sites.py. A change goes through the running core when there is one, so it is announced and loaded into the
front door at once; with none running, the core serves it at its next start."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import typer
from hiro_commons.log import Logger
from rich.console import Console
from rich.table import Table

from ..domain.workspace import WorkspaceError

log = Logger.get("CLI.SITES")

_WORKSPACE_HELP = "Workspace name (default: registry default)."


def _change(tool_name: str, params: dict[str, Any], workspace: str | None) -> tuple[Any, bool]:
    """Run the change in the running core when there is one, else here; (the result, it was live)."""
    from hiro_commons.process import is_running, read_pid

    from ..constants import PID_FILENAME
    from ..domain.workspace import resolve_workspace
    from ..domain.workspace_server_client import post_invoke_sync
    from ..tools.sites import SitesAddTool, SitesChangeResult, SitesRemoveTool

    entry, _ = resolve_workspace(workspace)
    workspace_path = Path(entry.path)
    if is_running(read_pid(workspace_path, PID_FILENAME)):
        out = post_invoke_sync(workspace_path, tool_name, {**params, "workspace": entry.id})
        return SitesChangeResult(**out), True
    tool = SitesAddTool() if tool_name == "sites_add" else SitesRemoveTool()
    return tool.execute(**params, workspace=workspace), False


def register(sites_app: typer.Typer, console: Console) -> None:
    """Register `hiro sites` commands."""

    @sites_app.command("list")
    def sites_list(
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Every name this machine serves: apps' names, extra names, the core's own and other sites."""
        from ..tools.sites import SitesListTool

        try:
            result = SitesListTool().execute(workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        table = Table(title=f"Names served (pointing at {result.ip or 'nothing: hiro extension names --ip'})")
        for column in ("Name", "Kind", "Owner", "Goes to", "Paths", "Announced"):
            table.add_column(column)
        for s in result.sites:
            table.add_row(s["name"], s["kind"], s["owner"], s["target"] or "(announced only)",
                          " ".join(s["paths"]) or "all", "yes" if s["announced"] else "no")
        console.print(table)

    @sites_app.command("add")
    def sites_add(
        name: str = typer.Argument(..., help="The name (adguard.local) or this machine's address (192.168.1.10)."),
        app: Optional[str] = typer.Option(None, "--app", help="An extra name for this app (its key: home)."),
        target: Optional[str] = typer.Option(None, "--target", help="Where it goes on this machine: 3001 or host:port."),
        path: Optional[list[str]] = typer.Option(None, "--path", help="Only this path goes to the target (repeat)."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Add an extra name beside an app's own (--app), or a site that is no app (--target, or neither to only
        announce the name)."""
        import httpx

        from ..domain.site_names import SiteNameError

        log.info("hiro sites add", name=name, app=app, target=target)
        params = {"name": name, "app": app, "target": target, "paths": list(path or [])}
        try:
            result, live = _change("sites_add", params, workspace)
        except (WorkspaceError, SiteNameError, RuntimeError, OSError, httpx.HTTPError) as exc:
            # The workspace unknown, the name refused, or the running server not answering (its words in the error).
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        if result.change == "refused":
            console.print(f"[red]{result.reason}[/red]")
            raise typer.Exit(1)
        goes = result.target or "announced only"
        if result.paths:
            goes += f", only {' '.join(result.paths)}"
        console.print(f"[green]Added[/green] [bold]{result.name}[/bold], which goes to {goes}")
        if not live:
            console.print("[dim]The core serves it at its next start.[/dim]")

    @sites_app.command("remove")
    def sites_remove(
        name: str = typer.Argument(..., help="The extra name or site to remove."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Remove an extra name or an other site (an app's own name goes with the app)."""
        import httpx

        from ..domain.site_names import SiteNameError

        log.info("hiro sites remove", name=name)
        try:
            result, live = _change("sites_remove", {"name": name}, workspace)
        except (WorkspaceError, SiteNameError, RuntimeError, OSError, httpx.HTTPError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        if result.change == "refused":
            console.print(f"[red]{result.reason}[/red]")
            raise typer.Exit(1)
        console.print(f"[green]Removed[/green] [bold]{result.name}[/bold].")
        if not live:
            console.print("[dim]The core stops serving it at its next start.[/dim]")
