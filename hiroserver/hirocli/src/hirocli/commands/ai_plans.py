"""``hiro ai plan …`` and ``hiro ai local …`` (Phase 7a Part B) — thin CLI over tools/ai_plans.py and tools/ai.py.

``hiro ai plan sign-in <tool>`` runs the whole sign-in in the terminal: it prints the link (Codex: and the
code to type there), and for Claude Code asks for the code Claude's page shows, then waits for the tool to
finish. The sign-in's program runs in this process; Ctrl-C stops it.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

import typer
from hiro_commons.log import Logger
from hiro_commons.timestamps import human_datetime
from rich.console import Console
from rich.table import Table

from ..domain.workspace import WorkspaceError

log = Logger.get("CLI.AI")

_WORKSPACE_HELP = "Workspace name (default: registry default)."
_TOOL_HELP = "claude_code or codex."
_POLL_S = 2.0
_SIGN_IN_WAIT_S = 15 * 60


def _human(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return human_datetime(datetime.fromisoformat(iso.replace("Z", "+00:00")))
    except ValueError:
        return iso


def _fail(console: Console, exc: Exception) -> None:
    console.print(f"[red]{exc}[/red]")
    raise typer.Exit(1) from exc


def _wait_signed_in(console: Console, tool: str, workspace: str | None) -> None:
    """Poll the sign-in until it ends; Ctrl-C cancels it."""
    from ..tools.ai_plans import PlanSignInTool

    deadline = time.monotonic() + _SIGN_IN_WAIT_S
    try:
        while time.monotonic() < deadline:
            out = PlanSignInTool().execute(tool=tool, action="state", workspace=workspace)
            if out.state != "waiting":
                if out.state == "done":
                    console.print(f"[green]Signed in.[/green]")
                else:
                    console.print(f"[yellow]{out.state}:[/yellow] {out.message or ''}")
                    raise typer.Exit(1)
                return
            time.sleep(_POLL_S)
    except KeyboardInterrupt:
        PlanSignInTool().execute(tool=tool, action="cancel", workspace=workspace)
        console.print("[yellow]Sign-in stopped.[/yellow]")
        raise typer.Exit(1) from None
    PlanSignInTool().execute(tool=tool, action="cancel", workspace=workspace)
    console.print("[yellow]Not finished within 15 minutes; start again.[/yellow]")
    raise typer.Exit(1)


def register(plan_app: typer.Typer, local_app: typer.Typer, console: Console) -> None:
    """Register ``hiro ai plan`` and ``hiro ai local`` commands."""

    @plan_app.command("status")
    def plan_status(
        tool: Optional[str] = typer.Argument(None, help=f"Only this tool: {_TOOL_HELP}"),
        fresh: bool = typer.Option(False, "--fresh", help="Read who is signed in now."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Show Claude Code / Codex: installed, signed in, models, updates."""
        from ..tools.ai_plans import PlanStatusTool

        try:
            result = PlanStatusTool().execute(tool=tool, fresh=fresh, workspace=workspace)
        except (WorkspaceError, ValueError) as exc:
            _fail(console, exc)
        table = Table(title="Plan tools", show_header=True)
        for col in ("Tool", "Version", "Signed in", "Plan", "Sign-in ends", "Models"):
            table.add_column(col)
        for t in result.tools:
            signed = "yes" if t["signed_in"] else (f"[yellow]{t['problem']}[/yellow]" if t["problem"] else "no")
            table.add_row(
                t["name"],
                t["version"] or "—",
                signed,
                t["plan"] or "—",
                _human(t["sign_in_ends_at"]),
                ", ".join(m["id"] for m in t["models"]) or (t["models_problem"] or "—"),
            )
        console.print(table)
        u = result.updates
        state = "running" if u["running"] else ("ok" if u["ok"] else (f"failed: {u['message']}" if u["ok"] is False else "never run"))
        console.print(f"Updates in {u['folder']}: last {_human(u['last_run'])} ({state}); next {_human(u['next_run'])}")

    @plan_app.command("sign-in")
    def plan_sign_in(
        tool: str = typer.Argument(..., help=_TOOL_HELP),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Sign a tool in with your plan (follow the link; Claude: paste the code back here)."""
        from ..services.plans.signin import SignInRefused
        from ..tools.ai_plans import PlanSignInTool

        log.info("hiro ai plan sign-in", tool=tool)
        try:
            out = PlanSignInTool().execute(tool=tool, action="start", workspace=workspace)
            for _ in range(15):  # the link shows after a moment
                if out.link or out.state != "waiting":
                    break
                time.sleep(1)
                out = PlanSignInTool().execute(tool=tool, action="state", workspace=workspace)
        except (WorkspaceError, ValueError) as exc:
            _fail(console, exc)
        except Exception as exc:  # NotInstalled / PlanToolError: the tool can't run here
            _fail(console, exc)
        if out.state != "waiting":
            console.print(f"[yellow]{out.state}:[/yellow] {out.message or ''}")
            raise typer.Exit(1)
        console.print(f"Open: [bold]{out.link or '(no link yet)'}[/bold]")
        if out.code:
            console.print(f"and type the code: [bold]{out.code}[/bold]")
        if out.takes_code:
            code = typer.prompt("Paste the code the page shows")
            try:
                PlanSignInTool().execute(tool=tool, action="code", code=code, workspace=workspace)
            except SignInRefused as exc:
                _fail(console, exc)
        _wait_signed_in(console, tool, workspace)

    @plan_app.command("sign-out")
    def plan_sign_out(
        tool: str = typer.Argument(..., help=_TOOL_HELP),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Sign a tool out of the core (your desktop's own tools stay signed in)."""
        from ..tools.ai_plans import PlanSignOutTool

        try:
            out = PlanSignOutTool().execute(tool=tool, workspace=workspace)
        except Exception as exc:  # unknown tool, not installed, tool failed
            _fail(console, exc)
        console.print("[green]Signed out.[/green]" if out.signed_out else f"[yellow]{out.message}[/yellow]")

    @plan_app.command("update")
    def plan_update(
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Install or update Claude Code and Codex with npm (needs Node.js and npm)."""
        from ..tools.ai_plans import PlanUpdateTool

        console.print("[dim]Running npm (the first install downloads about 500 MB)…[/dim]")
        try:
            out = PlanUpdateTool().execute(wait=True, workspace=workspace)
        except WorkspaceError as exc:
            _fail(console, exc)
        u = out.updates
        colour = "green" if u["ok"] else "red"
        console.print(f"[{colour}]{u['message']}[/{colour}]")
        if not u["ok"]:
            raise typer.Exit(1)

    @plan_app.command("test")
    def plan_test(
        tool: str = typer.Argument(..., help=_TOOL_HELP),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Ask a tool one short test question."""
        from ..tools.ai_plans import PlanTestTool

        try:
            out = PlanTestTool().execute(tool=tool, workspace=workspace)
        except Exception as exc:  # unknown tool, not installed, timeout
            _fail(console, exc)
        if out.ok:
            console.print(f"[green]{out.answer}[/green] [dim]({out.model or '?'}, {out.ms} ms)[/dim]")
        else:
            console.print(f"[red]{out.error}[/red]")
            raise typer.Exit(1)

    @local_app.command("status")
    def local_status(
        provider_id: str = typer.Argument(..., help="lm_studio or ollama."),
        base_url: Optional[str] = typer.Option(None, "--address", help="Save this address first."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Check a local server: up or down, its models, its settings (the list is kept for AI profiles)."""
        from ..tools.ai import LocalServerCheckTool

        try:
            r = LocalServerCheckTool().execute(provider_id=provider_id, base_url=base_url, workspace=workspace)
        except (WorkspaceError, ValueError) as exc:
            _fail(console, exc)
        state = "[green]up[/green]" if r.online else f"[yellow]{r.state}[/yellow] ({r.error})"
        console.print(f"{r.provider_id} at {r.base_url or '—'}: {state}")
        console.print(f"[dim]unload idle after {r.unload_idle_min} min · context {r.context} · batch {r.batch}[/dim]")
        for m in r.models:
            extras = ", ".join(
                x for x, on in (("pictures", m["vision"]), ("thinking", m["reasoning"]), ("loaded", m["loaded"])) if on
            )
            console.print(f"  [bold]{m['id']}[/bold]{f' ({extras})' if extras else ''}")

    @local_app.command("set")
    def local_set(
        provider_id: str = typer.Argument(..., help="lm_studio or ollama."),
        base_url: Optional[str] = typer.Option(None, "--address", help="Its address."),
        unload_idle_min: Optional[int] = typer.Option(None, "--unload-idle-min", help="Unload idle models after N minutes."),
        context: Optional[int] = typer.Option(None, "--context", help="Context length to load models with."),
        batch: Optional[int] = typer.Option(None, "--batch", help="Batch size to load models with."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Set a local server's address and how the core loads its models."""
        from ..tools.ai import LocalServerSetTool

        try:
            r = LocalServerSetTool().execute(
                provider_id=provider_id, base_url=base_url, unload_idle_min=unload_idle_min,
                context=context, batch=batch, workspace=workspace,
            )
        except Exception as exc:  # bad kind, out-of-bounds value (validation), workspace
            _fail(console, exc)
        console.print(
            f"{r.provider_id} at {r.base_url or '—'}: unload idle after {r.unload_idle_min} min · "
            f"context {r.context} · batch {r.batch}"
        )
