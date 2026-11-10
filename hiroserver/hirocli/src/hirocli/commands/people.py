"""People subcommands — thin CLI layer over the people tools (the plan's Phase 6).

The family list, its roles, and admin sign-ins. ``hiro people owner`` sets the
owner's sign-in from this machine (also how a forgotten password is reset);
passwords are always asked for, never given on the command line.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any, Optional

import typer
from hiro_commons.log import Logger
from rich.console import Console
from rich.table import Table

from ..domain.people import PeopleError
from ..domain.workspace import WorkspaceError

# Tool imports happen inside each command body to keep ``commands/app.py``
# import cheap on fast paths like ``hiro start``.

log = Logger.get("CLI.PEOPLE")

_WORKSPACE_HELP = "Workspace name (default: registry default)."


def _number(digits: str) -> str:
    return f"+{digits}" if digits else "—"


def _run(console: Console, call: Callable[[], Any]) -> Any:
    """Run a tool; a refused change or unknown workspace prints why and exits 1."""
    try:
        return call()
    except (PeopleError, WorkspaceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


def ask_password(console: Console) -> str:
    """Ask for a new password twice, hidden; needs a terminal."""
    if not sys.stdin.isatty():
        console.print("[red]A password is asked for in a terminal; run this command in one.[/red]")
        raise typer.Exit(1)
    return typer.prompt("Password (at least 8 characters)", hide_input=True, confirmation_prompt=True)


def register(people_app: typer.Typer, console: Console) -> None:
    """Register people commands."""

    @people_app.command("list")
    def people_list(
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """List the family and the roles."""
        from ..tools.people import PeopleListTool

        result = _run(console, lambda: PeopleListTool().execute(workspace=workspace))
        roles = {r["role_id"]: r["name"] for r in result.roles}
        if not result.people:
            console.print("[dim]Nobody in the family list yet. Start with `hiro people owner`.[/dim]")
        else:
            table = Table(title="People", show_header=True)
            table.add_column("Name", style="bold")
            table.add_column("Hiro calls them")
            table.add_column("Role")
            table.add_column("WhatsApp")
            table.add_column("Admin sign-in")
            table.add_column("ID", style="dim")
            for p in result.people:
                table.add_row(
                    p["name"],
                    p["calls_them"] or p["name"],
                    roles.get(p["role_id"], p["role_id"]),
                    _number(p["whatsapp"]),
                    p["sign_in"] or "no",
                    p["person_id"],
                )
            console.print(table)
        console.print("Roles: " + ", ".join(f"{r['name']} ({r['role_id']})" for r in result.roles))

    @people_app.command("add")
    def people_add(
        name: str = typer.Argument(..., help="Their name."),
        role: str = typer.Option(..., "--role", "-r", help="Role id: owner, adult, kid, …"),
        calls_them: Optional[str] = typer.Option(None, "--calls-them", help="What Hiro calls them."),
        whatsapp: Optional[str] = typer.Option(None, "--whatsapp", help="WhatsApp number with the country code."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Add a person to the family list."""
        from ..tools.people import PersonAddTool

        log.info("hiro people add", role=role)
        result = _run(
            console,
            lambda: PersonAddTool().execute(
                name=name, role_id=role, calls_them=calls_them, whatsapp=whatsapp, workspace=workspace
            ),
        )
        console.print(f"[green]Added[/green] [bold]{result.person['name']}[/bold] ({result.person['person_id']}).")

    @people_app.command("update")
    def people_update(
        person: str = typer.Argument(..., help="The person: id, name or sign-in name."),
        name: Optional[str] = typer.Option(None, "--name", help="New name."),
        role: Optional[str] = typer.Option(None, "--role", "-r", help="New role id."),
        calls_them: Optional[str] = typer.Option(None, "--calls-them", help="What Hiro calls them ('' = their name)."),
        whatsapp: Optional[str] = typer.Option(None, "--whatsapp", help="WhatsApp number ('' = none)."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Change a person's name, what Hiro calls them, role or number."""
        from ..tools.people import PersonUpdateTool

        log.info("hiro people update", role=role)
        result = _run(
            console,
            lambda: PersonUpdateTool().execute(
                person=person, name=name, role_id=role, calls_them=calls_them, whatsapp=whatsapp, workspace=workspace
            ),
        )
        console.print(f"[green]Saved[/green] [bold]{result.person['name']}[/bold].")

    @people_app.command("remove")
    def people_remove(
        person: str = typer.Argument(..., help="The person: id, name or sign-in name."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Remove a person from the family list."""
        from ..tools.people import PersonRemoveTool

        log.info("hiro people remove")
        _run(console, lambda: PersonRemoveTool().execute(person=person, workspace=workspace))
        console.print("[green]Removed.[/green]")

    @people_app.command("sign-in")
    def people_sign_in(
        person: str = typer.Argument(..., help="The person: id, name or sign-in name."),
        sign_in: str = typer.Option(..., "--as", help="The name they sign in with."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Give a person an admin sign-in, or reset their password."""
        from ..tools.people import PersonSignInTool

        password = ask_password(console)
        log.info("hiro people sign-in")
        result = _run(
            console,
            lambda: PersonSignInTool().execute(person=person, sign_in=sign_in, password=password, workspace=workspace),
        )
        console.print(
            f"[green]{result.person['name']} signs in to the admin as[/green] [bold]{result.person['sign_in']}[/bold]."
        )

    @people_app.command("sign-in-remove")
    def people_sign_in_remove(
        person: str = typer.Argument(..., help="The person: id, name or sign-in name."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Take a person's admin sign-in away."""
        from ..tools.people import PersonSignInRemoveTool

        log.info("hiro people sign-in-remove")
        result = _run(console, lambda: PersonSignInRemoveTool().execute(person=person, workspace=workspace))
        console.print(f"[green]{result.person['name']} no longer signs in to the admin.[/green]")

    @people_app.command("owner")
    def people_owner(
        name: Optional[str] = typer.Option(None, "--name", help="The owner's name (asked when omitted)."),
        sign_in: Optional[str] = typer.Option(None, "--as", help="The name they sign in with (asked when omitted)."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Set the owner's admin sign-in (first setup, or a forgotten password)."""
        set_owner_interactive(console, workspace=workspace, name=name, sign_in=sign_in)

    @people_app.command("role-add")
    def role_add(
        name: str = typer.Argument(..., help="The role's name."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Add a role."""
        from ..tools.people import RoleAddTool

        result = _run(console, lambda: RoleAddTool().execute(name=name, workspace=workspace))
        console.print(f"[green]Added role[/green] [bold]{result.role['name']}[/bold] ({result.role['role_id']}).")

    @people_app.command("role-rename")
    def role_rename(
        role_id: str = typer.Argument(..., help="The role's id."),
        name: str = typer.Argument(..., help="Its new name."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Rename a role (not Owner)."""
        from ..tools.people import RoleRenameTool

        _run(console, lambda: RoleRenameTool().execute(role_id=role_id, name=name, workspace=workspace))
        console.print("[green]Renamed.[/green]")

    @people_app.command("role-admin")
    def role_admin(
        role_id: str = typer.Argument(..., help="The role's id."),
        off: bool = typer.Option(False, "--off", help="Switch it off instead."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Let a role open HiroLeague's settings (--off: only the apps). Owner always can."""
        from ..tools.people import RoleAdminTool

        _run(console, lambda: RoleAdminTool().execute(role_id=role_id, admin=not off, workspace=workspace))
        console.print("[green]Switched off.[/green]" if off else "[green]Switched on.[/green]")

    @people_app.command("role-remove")
    def role_remove(
        role_id: str = typer.Argument(..., help="The role's id."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Remove a role nobody has (not Owner)."""
        from ..tools.people import RoleRemoveTool

        _run(console, lambda: RoleRemoveTool().execute(role_id=role_id, workspace=workspace))
        console.print("[green]Removed.[/green]")

    # Phase 9a: what each role may do, per source (HiroLeague and each extension).

    @people_app.command("access")
    def access(
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Show each role's rights in HiroLeague and in each extension."""
        from ..tools.people import AccessListTool

        result = _run(console, lambda: AccessListTool().execute(workspace=workspace))
        for source in result.sources:
            table = Table(title=f"{source['name']} ({source['id']})")
            table.add_column("Right")
            for role in result.roles:
                table.add_column(role["name"])
            for feature in source["features"]:
                for right in feature["rights"]:
                    key = f"{feature['id']}.{right['id']}"
                    marks = ["yes" if key in role["rights"].get(source["id"], []) else "" for role in result.roles]
                    table.add_row(f"{feature['name']}: {right['name']} ({key})", *marks)
            console.print(table)

    @people_app.command("role-rights")
    def role_rights(
        role_id: str = typer.Argument(..., help="The role's id."),
        source: str = typer.Argument(..., help="hiroleague, or the extension's name."),
        rights: list[str] = typer.Argument(None, help='Right keys "<feature>.<right>"; none = take every right away.'),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Give a role exactly these rights in HiroLeague or one extension (see `hiro people access`)."""
        from ..tools.people import RoleRightsTool

        result = _run(
            console,
            lambda: RoleRightsTool().execute(role_id=role_id, source=source, rights=list(rights or []), workspace=workspace),
        )
        console.print(f"[green]Saved.[/green] {result.role['name']} in {source}.")

    @people_app.command("role-says")
    def role_says(
        role_id: str = typer.Argument(..., help="The role's id."),
        says: str = typer.Argument(..., help="One line on what the role is for."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Set the one line on what a role is for."""
        from ..tools.people import RoleSaysTool

        _run(console, lambda: RoleSaysTool().execute(role_id=role_id, says=says, workspace=workspace))
        console.print("[green]Saved.[/green]")


def set_owner_interactive(
    console: Console, *, workspace: str | None, name: str | None = None, sign_in: str | None = None
) -> None:
    """Ask for the owner's name, sign-in name and password, and set them (``hiro people owner``, setup)."""
    from ..tools.people import OwnerSignInTool

    if not sys.stdin.isatty() and (name is None or sign_in is None):
        console.print("[red]Run this in a terminal: it asks for the owner's name and password.[/red]")
        raise typer.Exit(1)
    name = name or typer.prompt("Owner's name")
    sign_in = sign_in or typer.prompt("Sign-in name", default=name.split()[0].lower())
    password = ask_password(console)
    log.info("hiro people owner")
    result = _run(
        console, lambda: OwnerSignInTool().execute(name=name, sign_in=sign_in, password=password, workspace=workspace)
    )
    console.print(
        f"[green]{result.person['name']} (Owner) signs in to the admin as[/green] "
        f"[bold]{result.person['sign_in']}[/bold]."
    )
