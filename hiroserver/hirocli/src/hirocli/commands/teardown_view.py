"""How the CLI shows a teardown (tools/teardown.py): what will happen to which workspace, asked before anything is
done; then what was done, and what was left and why (issue 430)."""

from __future__ import annotations

import typer
from rich.console import Console

from ..tools.teardown import TeardownPlan, WorkspaceTeardown


def confirm_plan(console: Console, plan: TeardownPlan, *, yes: bool) -> None:
    """Print each line of the plan and ask to go on (unless --yes); stop the command on no."""
    lines = plan.lines()
    if not lines:
        return
    console.print("[bold]This will:[/bold]")
    for line in lines:
        console.print(f"  • {line}")
    if not yes:
        typer.confirm("Go on?", abort=True)


def print_outcome(console: Console, plan: TeardownPlan) -> bool:
    """What was done to each; False when something was left (a service only an administrator can remove)."""
    all_done = True
    for item in [*plan.workspaces, *plan.gateways]:
        kind = "Workspace" if isinstance(item, WorkspaceTeardown) else "Gateway"
        if item.problem:
            all_done = False
            console.print(f"[yellow]{kind} '{item.name}' left as it was: {item.problem}.[/yellow]")
        elif item.done:
            console.print(f"[green]{kind} '{item.name}':[/green] {', '.join(item.done)}.")
        else:
            console.print(f"{kind} '{item.name}': nothing to do.")
    return all_done

