"""Log reading subcommands — thin CLI layer over the log tools (tools/logs.py): search, tail, and the two questions that
answer across the core and every app, problems (what went wrong in a span) and story (everything one id did).

`--json` prints a tool's whole result as JSON (UTF-8), for an agent: a Claude session on the PC runs
`hiro logs problems --since 1h --json` (or over `ssh simone` for the live core).
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

from ..domain.workspace import WorkspaceError

# Tool imports happen inside each command body to keep ``commands/app.py``
# import cheap on fast paths like ``hiro start``.

_SOURCE_HELP = (
    "Log source: all (the core and every app, the default), core, server, channels, gateway, cli, apps, "
    "or one app by its name (home, net)."
)
_LEVEL_STYLES = {
    "DEBUG": "blue",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "bold magenta",
}


def _print_json(result: Any) -> None:
    """The result as JSON, written as UTF-8 bytes (a Windows console's code page can't take every character)."""
    sys.stdout.buffer.write((json.dumps(asdict(result), ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    sys.stdout.flush()


def _console_safe() -> None:
    """A Windows console's code page can't show every character (the core's lines carry emoji): one it can't show
    prints as "?" rather than ending the command half way."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None and (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
        reconfigure(errors="replace")


def _level(lvl: str) -> str:
    style = _LEVEL_STYLES.get(lvl, "")
    return f"[{style}]{lvl}[/{style}]" if style else lvl


def register(logs_app: typer.Typer, console: Console) -> None:
    """Register log subcommands on *logs_app*."""

    @logs_app.command("search")
    def logs_search(
        query: Optional[str] = typer.Argument(
            None, help="Full-text search across message and extra fields."
        ),
        source: Optional[str] = typer.Option(
            None,
            "--source",
            "-s",
            help=_SOURCE_HELP,
        ),
        level: Optional[str] = typer.Option(
            None,
            "--level",
            "-l",
            help="Minimum log level: DEBUG, INFO, WARNING, ERROR, CRITICAL.",
        ),
        module: Optional[str] = typer.Option(
            None,
            "--module",
            "-m",
            help="Filter by module name (substring match).",
        ),
        story_id: Optional[str] = typer.Option(
            None,
            "--story",
            help="Only this story's lines (its id, a traceparent, or a chat message's id).",
        ),
        as_json: bool = typer.Option(False, "--json", help="Print the result as JSON (for agents)."),
        limit: Optional[int] = typer.Option(
            None,
            "--limit",
            "-n",
            help="Maximum rows to return (default: 200).",
        ),
        workspace: Optional[str] = typer.Option(
            None,
            "--workspace",
            "-W",
            help="Workspace name (default: registry default).",
        ),
    ) -> None:
        """Search log files for entries matching the given filters."""
        from ..tools.logs import LogSearchTool

        try:
            result = LogSearchTool().execute(
                source=source,
                level=level,
                module=module,
                query=query,
                limit=limit,
                workspace=workspace,
                story_id=story_id,
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc

        if as_json:
            from ..tools.logs import brief

            result.rows = [brief(r) for r in result.rows]
            _print_json(result)
            return
        if not result.rows:
            console.print("[dim]No matching log entries found.[/dim]")
            return

        table = Table(show_header=True, box=None)
        table.add_column("Time", style="dim", no_wrap=True)
        table.add_column("Lvl", no_wrap=True)
        table.add_column("Source", style="cyan", no_wrap=True)
        table.add_column("Module", style="magenta", no_wrap=True)
        table.add_column("Message")
        table.add_column("Extra", style="dim")

        _LEVEL_STYLES = {
            "DEBUG": "blue",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold magenta",
        }

        for row in result.rows:
            lvl = row.get("level", "")
            lvl_style = _LEVEL_STYLES.get(lvl, "")
            table.add_row(
                row.get("timestamp", ""),
                f"[{lvl_style}]{lvl}[/{lvl_style}]" if lvl_style else lvl,
                row.get("source", ""),
                row.get("module", ""),
                row.get("message", ""),
                row.get("extra", ""),
            )

        console.print(table)

        if result.truncated:
            console.print(
                f"[dim]Showing {len(result.rows)} of {result.total_matches} matches "
                f"— use --limit to increase.[/dim]"
            )

    @logs_app.command("tail")
    def logs_tail(
        lines: int = typer.Option(
            100,
            "--lines",
            "-n",
            help="Number of recent lines to show.",
        ),
        source: Optional[str] = typer.Option(
            None,
            "--source",
            "-s",
            help=_SOURCE_HELP,
        ),
        workspace: Optional[str] = typer.Option(
            None,
            "--workspace",
            "-W",
            help="Workspace name (default: registry default).",
        ),
    ) -> None:
        """Show the most recent log entries."""
        from ..tools.logs import LogTailTool

        try:
            result = LogTailTool().execute(
                source=source,
                lines=lines,
                workspace=workspace,
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc

        if not result.rows:
            console.print("[dim]No log entries found.[/dim]")
            return

        _LEVEL_STYLES = {
            "DEBUG": "blue",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold magenta",
        }

        for row in result.rows:
            lvl = row.get("level", "")
            lvl_style = _LEVEL_STYLES.get(lvl, "")
            lvl_display = f"[{lvl_style}]{lvl[:3]}[/{lvl_style}]" if lvl_style else lvl[:3]
            console.print(
                f"[dim]{row.get('timestamp', '')}[/dim] "
                f"{lvl_display} "
                f"[cyan]{row.get('source', '')}[/cyan] "
                f"[magenta]{row.get('module', '')}[/magenta] "
                f"{row.get('message', '')} "
                f"[dim]{row.get('extra', '')}[/dim]"
            )

    @logs_app.command("problems")
    def logs_problems(
        since: str = typer.Option("1h", "--since", help="Start of the span: back from now (1h, 30m, 2d) or an ISO time."),
        until: Optional[str] = typer.Option(None, "--until", help="End of the span (default: now)."),
        level: Optional[str] = typer.Option(None, "--level", "-l", help="Lowest level: WARNING (default), ERROR."),
        source: Optional[str] = typer.Option(None, "--source", "-s", help=_SOURCE_HELP),
        limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Problem lines to return (default 100)."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help="Workspace name (default: registry default)."),
        as_json: bool = typer.Option(False, "--json", help="Print the result as JSON (for agents)."),
    ) -> None:
        """What went wrong in a span of time, across the core and every app."""
        from ..tools.logs import LogProblemsTool

        _console_safe()

        try:
            result = LogProblemsTool().execute(since=since, until=until, level=level, source=source, limit=limit,
                                               workspace=workspace)
        except (WorkspaceError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        if as_json:
            _print_json(result)
            return
        console.print(f"[bold]Problems[/bold] {result.span}")
        if not result.total:
            console.print("[dim]Nothing went wrong.[/dim]")
            return
        console.print("  " + " · ".join(f"[cyan]{src}[/cyan] {n}" for src, n in result.by_source.items()))
        for g in result.groups:  # one line each, then its latest messages: a table squeezes them to nothing
            kinds = f", {g['kinds']} kinds" if g["kinds"] > 1 else ""
            console.print(
                f"{g['count']:>4}× {_level(g['level'])} [cyan]{g['source']}[/cyan] [magenta]{g['area']}[/magenta] "
                f"[dim](last {g['last']}{kinds})[/dim]",
                highlight=False,
            )
            for message in g["messages"]:
                console.print(f"        {message}", markup=False, highlight=False)
        console.print("[dim]Follow one with: hiro logs story <story id> (each line's story id is in --json).[/dim]")

    @logs_app.command("story")
    def logs_story(
        story_id: str = typer.Argument(..., help="The story's id, a traceparent, or a chat message's id."),
        limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Lines at most (default 1000)."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help="Workspace name (default: registry default)."),
        as_json: bool = typer.Option(False, "--json", help="Print the result as JSON (for agents)."),
    ) -> None:
        """Everything one story did, across the core and every app, in order."""
        from ..tools.logs import LogStoryTool

        _console_safe()

        try:
            result = LogStoryTool().execute(story_id=story_id, limit=limit, workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        if as_json:
            _print_json(result)
            return
        if not result.rows:
            console.print(f"[dim]No lines for story {result.story_id}.[/dim]")
            return
        console.print(
            f"[bold]Story {result.story_id}[/bold] · {result.started} · {result.took_ms} ms · "
            f"through {', '.join(result.sources)} · {result.problems} problem(s)"
        )
        for row in result.rows:
            fields = " ".join(f"{k}={v}" for k, v in (row.get("fields") or {}).items())
            console.print(
                f"[dim]{row['when']}[/dim] {_level(row['level'])} [cyan]{row['source']}[/cyan] "
                f"[magenta]{row['area']}[/magenta] {row['message']} [dim]{fields}[/dim]",
                markup=True, highlight=False,
            )
