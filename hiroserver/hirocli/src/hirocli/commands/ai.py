"""AI subcommands (Phase 7a) — thin CLI layer over the AI tools (tools/ai.py).

``hiro ai list`` (profiles), ``hiro ai try``, ``hiro ai uses list|set|forget|refresh``,
``hiro ai import-homehiro``; plan tools and local servers in commands/ai_plans.py
(``hiro ai plan …``, ``hiro ai local …``). Profiles are edited in the admin (Catalog, AI profiles) or in
preferences.json (``ai.profiles``).
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from hiro_commons.log import Logger
from hiro_commons.timestamps import human_datetime
from rich.console import Console
from rich.table import Table

from ..domain.workspace import WorkspaceError

# Tool imports happen inside each command body to keep ``commands/app.py`` import cheap.

log = Logger.get("CLI.AI")

_WORKSPACE_HELP = "Workspace name (default: registry default)."


def _human(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return human_datetime(datetime.fromisoformat(iso.replace("Z", "+00:00")))
    except ValueError:
        return iso


def _cost(value: float | None) -> str:
    return "—" if value is None else f"${value:.4f}"


def register(ai_app: typer.Typer, uses_app: typer.Typer, console: Console) -> None:
    """Register ``hiro ai`` and ``hiro ai uses`` commands."""

    @ai_app.command("list")
    def ai_list(
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """List the AI profiles."""
        from ..tools.ai import AiProfilesListTool

        try:
            result = AiProfilesListTool().execute(workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        if not result.profiles:
            console.print("[dim]No AI profiles yet. Add one in the admin: Catalog, AI profiles.[/dim]")
            return
        table = Table(title="AI profiles", show_header=True)
        table.add_column("ID", style="bold")
        table.add_column("Name")
        table.add_column("Model")
        table.add_column("Kind")
        table.add_column("Limits")
        table.add_column("Today")
        table.add_column("Falls back to")
        table.add_column("Ready")
        for p in result.profiles:
            today = p["today"]
            table.add_row(
                p["id"],
                p["label"],
                p["model"],
                p["kind"],
                p["budget_hint"],
                f"{today['asks']} asks, {_cost(today['cost'])}",
                " -> ".join(p["fallback_chain"]) or "—",
                "yes" if p["ready"] else f"[yellow]{p['not_ready']}[/yellow]",
            )
        console.print(table)

    @ai_app.command("try")
    def ai_try(
        prompt: str = typer.Argument(..., help="The question."),
        profile_id: str = typer.Option(..., "--profile", "-p", help="AI profile id (see `hiro ai list`)."),
        picture: Optional[Path] = typer.Option(None, "--picture", help="A JPEG to ask about."),
        schema: Optional[str] = typer.Option(None, "--schema", help="JSON schema for the answer (default: {answer})."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Ask an AI profile one question (counts toward its limits)."""
        from ..tools.ai import AiTryTool

        picture_b64: str | None = None
        if picture is not None:
            path = picture.expanduser().resolve()
            if not path.is_file():
                console.print(f"[red]Picture not found:[/red] {path}")
                raise typer.Exit(1)
            picture_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        log.info("hiro ai try", profile_id=profile_id)
        try:
            result = AiTryTool().execute(
                prompt=prompt, profile_id=profile_id, picture=picture_b64, schema=schema, workspace=workspace
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        if not result.ok or result.answer is None:
            err = result.error or {}
            console.print(f"[red]Not answered ({err.get('code')}):[/red] {err.get('message')}")
            raise typer.Exit(1)
        a = result.answer
        try:
            shown = json.dumps(json.loads(a["text"]), indent=2, ensure_ascii=False)
        except ValueError:
            shown = a["text"]
        console.print(shown)
        console.print(
            f"[dim]{a['profile_name']} · {a['provider']}:{a['model']} · {a['ms']} ms · "
            f"{a['tokens_in']} in / {a['tokens_out']} out · {_cost(a['cost'])}[/dim]"
        )
        for note in a["notes"]:
            console.print(f"[yellow]passed over:[/yellow] {note}")

    @ai_app.command("import-homehiro")
    def ai_import_homehiro(
        db_path: Path = typer.Argument(..., help="A copy of HomeHiro's homehiro.db."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Only show what would be written."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Import HomeHiro's LLM profiles, defaults and local servers as AI profiles (once)."""
        from ..services.ai_ask.import_homehiro import ImportError_
        from ..tools.ai import AiImportHomeHiroTool

        log.info("hiro ai import-homehiro", dry_run=dry_run)
        try:
            result = AiImportHomeHiroTool().execute(db_path=str(db_path), dry_run=dry_run, workspace=workspace)
        except (WorkspaceError, ImportError_, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        verb = "Would write" if dry_run else "Wrote"
        console.print(f"[bold]{verb}[/bold] {len(result.profiles)} AI profiles (ids hh-<HomeHiro profile id>, as HomeHiro's copies send them):")
        back = {new: old for old, new in result.from_ids.items()}
        for pid, f in result.profiles.items():
            fallback = f" -> falls back to {f['fallback']}" if f.get("fallback") else ""
            source = f" (HomeHiro {back[pid]})" if pid in back else ""
            console.print(f"  [bold]{pid}[/bold] {f['label']}: {f['model']}{source}{fallback}")
        for key, pid in result.uses.items():
            console.print(f"  use [bold]{key}[/bold] -> {pid}")
        for kind, address in result.servers.items():
            console.print(f"  {kind} address {address}")
        for note in result.notes:
            console.print(f"[yellow]note:[/yellow] {note}")
        if not dry_run:
            console.print("[dim]Sign Claude Code / Codex in again here: hiro ai plan sign-in <tool>.[/dim]")

    @ai_app.command("import-homehiro-usage")
    def ai_import_homehiro_usage(
        db_path: Path = typer.Argument(..., help="A copy of HomeHiro's homehiro.db."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Only show what would be added."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Phase 7b: add HomeHiro's LLM usage history to the core's AI usage (once; safe to run again)."""
        from ..services.ai_usage.import_homehiro import UsageImportError
        from ..tools.ai import AiUsageImportHomeHiroTool

        log.info("hiro ai import-homehiro-usage", dry_run=dry_run)
        try:
            r = AiUsageImportHomeHiroTool().execute(db_path=str(db_path), dry_run=dry_run, workspace=workspace)
        except (WorkspaceError, UsageImportError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        verb = "Would add" if dry_run else "Added"
        span = f" ({r.first_hour} to {r.last_hour}, UTC hours)" if r.first_hour else ""
        console.print(
            f"[bold]{verb}[/bold] {r.imported} of HomeHiro's {r.rows} usage rows{span}: "
            f"{r.requests} requests, {_cost(r.cost)}."
        )
        for note in r.notes:
            console.print(f"[yellow]note:[/yellow] {note}")

    @uses_app.command("list")
    def uses_list(
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """List each extension's AI uses and the profile each one asks."""
        from ..tools.ai import AiUsesListTool

        try:
            result = AiUsesListTool().execute(workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        if not result.extensions:
            console.print("[dim]No extension has declared AI uses yet.[/dim]")
            return
        for ext in result.extensions:
            table = Table(title=f"{ext['extension']} (as of {_human(ext['as_of'])})", show_header=True)
            table.add_column("Use", style="bold")
            table.add_column("Name")
            table.add_column("Takes")
            table.add_column("Profile")
            table.add_column("")
            for u in ext["uses"]:
                takes = ", ".join(
                    x
                    for x, on in ((f"{u['pictures']} pictures", u["pictures"]), ("sound", u["sound"]), ("JSON", u["json"]))
                    if on
                )
                table.add_row(u["key"], u["name"], takes or "words", u["profile_id"] or "—", u["status"])
            console.print(table)

    @ai_app.command("restore-default")
    def ai_restore_default(
        profile_id: str = typer.Argument(..., help="A job's default AI profile (e.g. hiro-chat)."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Put a job's default AI profile back to its preset tuning (its model stays)."""
        from ..tools.ai import AiProfileRestoreDefaultTool

        try:
            result = AiProfileRestoreDefaultTool().execute(profile_id=profile_id, workspace=workspace)
        except (WorkspaceError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        console.print(f"[green]{result.profile_id}[/green] back to the {result.preset} job's default tuning")

    @uses_app.command("set")
    def uses_set(
        key: str = typer.Argument(..., help="The use, <extension>:<use id> (e.g. home:ask)."),
        profile_id: Optional[str] = typer.Argument(None, help="AI profile id; omit to clear the pick."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Point a use at an AI profile."""
        from ..tools.ai import AiUsesSetTool

        try:
            result = AiUsesSetTool().execute(key=key, profile_id=profile_id, workspace=workspace)
        except (WorkspaceError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        console.print(f"[green]{result.key}[/green] -> {result.profile_id or 'no profile'}")

    @uses_app.command("forget")
    def uses_forget(
        key: str = typer.Argument(..., help="The use, <extension>:<use id>."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Forget a use an extension no longer declares."""
        from ..tools.ai import AiUsesForgetTool

        try:
            result = AiUsesForgetTool().execute(key=key, workspace=workspace)
        except (WorkspaceError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        console.print(f"[green]Forgot[/green] {result.key}" if result.forgotten else f"[yellow]No use {result.key}[/yellow]")

    @uses_app.command("refresh")
    def uses_refresh(
        extension_id: Optional[str] = typer.Argument(None, help="Only this extension id; all connected when omitted."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Ask connected extensions for their AI uses again (needs the running server)."""
        from ..domain.workspace import resolve_workspace
        from ..domain.workspace_server_client import post_invoke_sync

        try:
            entry, _ = resolve_workspace(workspace)
            out = post_invoke_sync(Path(entry.path), "ai_uses_refresh", {"extension_id": extension_id})
        except Exception as exc:  # not running, transport error, or the tool's own error
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        if out.get("note"):
            console.print(f"[dim]{out['note']}[/dim]")
        for r in out.get("refreshed") or []:
            console.print(f"[green]{r['extension']}[/green]: {r['uses']} uses")
        for f in out.get("failed") or []:
            console.print(f"[yellow]{f['extension']}[/yellow]: {f['error']}")
