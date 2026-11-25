"""`hiro service`: run the Hiro server as a system service (install, uninstall, status, start, stop).

Linux: a systemd system service (root, through sudo). Windows: a Windows service under WinSW (an administrator; from a
normal terminal the command asks for one UAC prompt and runs itself again elevated). Mac: a LaunchDaemon (root,
through sudo).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import typer
from hiro_commons.log import Logger
from hiro_commons.systemd_service import NeedsRootError, ServiceError
from hiro_commons.timestamps import human_datetime
from rich.console import Console

from ..domain.workspace import WorkspaceRegistry, admin_port_for

log = Logger.get("CLI.SERVICE")

# The elevated run writes its outcome here: its own window closes when it ends, and this terminal shows it.
_REPORT_HELP = "Where an elevated run writes its outcome (used by the command itself)."


def _first_admin_port() -> int:
    # The first workspace's admin port (slot 0); only used in the "next steps" hint, since the
    # service user's own workspace registry may not be readable from here.
    return admin_port_for(WorkspaceRegistry(), 0)


def _print_needs_root(console: Console, exc: NeedsRootError) -> None:
    console.print(f"[yellow]{exc.action} needs root.[/yellow]")
    console.print(f"{exc.why} Run:")
    console.print(f"  [bold cyan]{exc.command}[/bold cyan]")


def _write_report(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    try:
        Path(path).write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        log.warning("⚠️ Could not write the elevated run's outcome — HiroServer · service", path=path, exc_info=True)


def _run(console: Console, action: str, report: str | None, call, argv: list[str]) -> Any:
    """Run one service operation; on Windows without an administrator, run it again elevated (one UAC prompt).

    Returns the operation's result as a dict (the elevated run's comes back through its report file).
    """
    try:
        result = asdict(call())
    except NeedsRootError as exc:
        _print_needs_root(console, exc)
        raise typer.Exit(1) from exc
    except ServiceError as exc:
        from hiro_commons.winsw_service import NeedsAdminError

        if isinstance(exc, NeedsAdminError) and report is None:
            return _elevate(console, exc, argv)
        _write_report(report, {"ok": False, "error": str(exc)})
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    except Exception as exc:
        if report is None:
            raise  # a normal run: the CLI's own net logs it with its traceback
        # The elevated run's window closes when it ends: whatever went wrong must reach the terminal that asked.
        log.error("❌ The elevated service command failed — HiroServer · service", action=action, exc_info=True)
        _write_report(report, {"ok": False, "error": f"Something went wrong ({type(exc).__name__}); see the CLI's log."})
        raise typer.Exit(1) from exc
    _write_report(report, {"ok": True, "result": result})
    return result


def _elevate(console: Console, exc, argv: list[str]) -> dict[str, Any]:
    from hiro_commons.winsw_service import ElevationRefused, run_elevated

    from ..linux_service import hiro_executable

    console.print(f"[yellow]{exc.action} needs an administrator:[/yellow] Windows will ask (one prompt).")
    fd, report_path = tempfile.mkstemp(prefix="hiro-service-", suffix=".json")
    os.close(fd)
    try:
        code = run_elevated([hiro_executable(), "service", *argv, "--report", report_path])
        try:
            payload = json.loads(Path(report_path).read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            payload = {}
    except ElevationRefused as refused:
        console.print(f"[yellow]{refused}[/yellow]")
        console.print(f"To run it yourself, from an administrator terminal:\n  [bold cyan]{exc.command}[/bold cyan]")
        raise typer.Exit(1) from refused
    except ServiceError as failed:
        console.print(f"[red]{failed}[/red]")
        raise typer.Exit(1) from failed
    finally:
        Path(report_path).unlink(missing_ok=True)
    if payload.get("ok"):
        return payload["result"]
    console.print(f"[red]{payload.get('error') or f'The elevated run ended with exit code {code} and said nothing.'}[/red]")
    raise typer.Exit(1)


def _argv(action: str, **options: str | None) -> list[str]:
    out = [action]
    for flag, value in options.items():
        if value:
            out += [f"--{flag.replace('_', '-')}", value]
    return out


def register(service_app: typer.Typer, console: Console) -> None:
    """Register `hiro service` subcommands."""

    @service_app.command("install")
    def install(
        user: Optional[str] = typer.Option(
            None, "--user", "-u",
            help="Linux and Mac: the account the service runs as, your own or a dedicated one such as 'hiro'. "
                 "Default: the user running the install. (Windows: always its own account, NT SERVICE\\hiro.)",
        ),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace to run (default: the service's default workspace, created on first start).",
        ),
        home: Optional[str] = typer.Option(
            None, "--home", help="Windows: the folder for the program and its Python (default: %ProgramData%\\HiroLeague).",
        ),
        data_dir: Optional[str] = typer.Option(
            None, "--data-dir", help="Windows: the folder for the workspace, on an NTFS disk (default: <home>\\data).",
        ),
        source: Optional[str] = typer.Option(
            None, "--from",
            help="Windows: what to install for the service, a package or a checkout's path "
                 "(default: this version of hiroleague).",
        ),
        core_name: Optional[str] = typer.Option(
            None, "--name",
            help="The core's name, for the service's new workspace: its admin at <name>.local and its apps at "
                 "<app>.<name>.local (default: hiro). A workspace that exists keeps its own.",
        ),
        report: Optional[str] = typer.Option(None, "--report", hidden=True, help=_REPORT_HELP),
    ) -> None:
        """Install the Hiro server as a system service: starts at boot, restarts on failure."""
        log.info("hiro service install", user=user, workspace=workspace, home=home, data_dir=data_dir, source=source,
                 core_name=core_name)
        from ..domain.site_names import SiteNameError, check_core_name
        from ..tools.service import ServiceInstallTool

        if core_name:
            try:
                check_core_name(core_name)
            except SiteNameError as exc:  # said before anything is installed or an admin is asked
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1) from exc
        result = _run(
            console, "install", report,
            lambda: ServiceInstallTool().execute(
                user=user, workspace=workspace, home=home, data_dir=data_dir, source=source, core_name=core_name,
            ),
            _argv("install", user=user, home=home, data_dir=data_dir, **{"from": source}, workspace=workspace,
                  name=core_name),
        )
        console.print(
            f"[green]✅ HiroLeague service installed and started:[/green] [bold]{result['service']}[/bold] "
            f"(runs as [bold]{result['user']}[/bold], starts at boot, restarts if it fails)."
        )
        console.print(f"  Runs:    {result['exec_start']}")
        console.print(f"  Service: {result['definition_path']}")
        if result.get("data_dir"):
            console.print(f"  Data:    {result['data_dir']}")
        if core_name:
            console.print(f"  Name:    {core_name.strip().lower()} [dim](a new workspace's: its admin at "
                          f"{core_name.strip().lower()}.local; a workspace that exists keeps its own)[/dim]")
        if result["secrets_file_created"]:
            console.print(f"  Secrets: {result['secrets_file']} [dim](new; only the service and administrators can read it)[/dim]")
        else:
            console.print(f"  Secrets: {result['secrets_file']} [dim](kept as it was)[/dim]")
        if result.get("front_door"):
            console.print(f"  Front door: {result['front_door']} [dim](Caddy on port 80, runs as "
                          f"{result['front_door_account']}; the core loads every name into it)[/dim]")
        for rule in result.get("firewall") or []:
            console.print(f"  Firewall:   {rule}")
        port = _first_admin_port()
        console.print("\n[bold]Next steps[/bold]")
        console.print(f"  1. Add your provider API keys:  [cyan]{result['edit_secrets']}[/cyan]  (e.g. OPENAI_API_KEY=...)")
        console.print(f"  2. Load them:                   [cyan]{result['restart_command']}[/cyan]")
        if result["manager"] == "systemd":
            console.print(
                f"  3. Open the admin UI. It listens on this machine only (port {port} for the first workspace); "
                f"from another computer: [cyan]ssh -L {port}:localhost:{port} <this-server>[/cyan], "
                f"then http://localhost:{port}"
            )
        else:
            console.print(f"  3. Open the admin UI on this computer: http://localhost:{port}")
        console.print(
            "     In Providers/Models → Providers, click [bold]Scan environment[/bold] once to turn on the providers "
            "whose keys you added."
        )
        console.print(f"\n  State: [cyan]hiro service status[/cyan] · Logs: [cyan]{result['logs']}[/cyan]")

    @service_app.command("uninstall")
    def uninstall(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace whose service to remove (default: the default service).",
        ),
        report: Optional[str] = typer.Option(None, "--report", hidden=True, help=_REPORT_HELP),
    ) -> None:
        """Stop and remove the service. Keeps the workspace, the program and the secrets file."""
        log.info("hiro service uninstall", workspace=workspace)
        from ..tools.service import ServiceUninstallTool

        result = _run(
            console, "uninstall", report,
            lambda: ServiceUninstallTool().execute(workspace=workspace),
            _argv("uninstall", workspace=workspace),
        )
        if result["removed"]:
            console.print(f"[green]Service removed:[/green] {result['service']} is stopped and no longer starts at boot.")
        else:
            console.print(f"[yellow]{result['service']} is not installed; nothing to remove.[/yellow]")
        if result.get("front_door_removed"):
            console.print("The front door (Caddy) was removed too: nothing on this machine answers on port 80 now.")
        console.print("[dim]Your workspace (data, settings) was not touched.[/dim]")
        for folder in result.get("kept") or []:
            console.print(f"Kept: {folder}")
        if result["secrets_file"]:
            console.print(
                f"The secrets file was kept: {result['secrets_file']}. Delete it if you no longer need it: "
                f"[cyan]{result['delete_secrets']}[/cyan]"
            )

    @service_app.command("status")
    def status(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace whose service to show (default: the default service).",
        ),
    ) -> None:
        """Show whether the service is installed, running, and started at boot."""
        from ..tools.service import ServiceStatusTool

        try:
            result = ServiceStatusTool().execute(workspace=workspace)
        except ServiceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc

        if not result.installed:
            console.print(f"[yellow]{result.service} is not installed.[/yellow] Install it with:")
            console.print(f"  [cyan]{result.install_command}[/cyan]")
            raise typer.Exit(1)

        colour = "green" if result.running else ("red" if result.state.lower() == "failed" else "yellow")
        state = f"[{colour}]{result.state}[/{colour}]"
        if result.detail:
            state += f" ({result.detail})"
        if result.active_since_iso and result.running:
            state += f" since {human_datetime(datetime.fromisoformat(result.active_since_iso))}"
        console.print(f"[bold]{result.service}[/bold]: {state}")
        if result.main_pid:
            console.print(f"  PID:      {result.main_pid}")
        console.print(f"  Runs as:  {result.user or '[red]root (not supported)[/red]'}")
        boot = "yes" if result.at_boot else f"no ({result.boot_detail})"
        console.print(f"  At boot:  {boot}")
        if result.restarts is not None:
            console.print(f"  Restarts: {result.restarts} since it was last started by hand")
        if result.definition_path:
            console.print(f"  Service:  {result.definition_path}")
        console.print(f"  Secrets:  {result.secrets_file or '[red]missing: the service cannot start without it[/red]'}")
        if result.logs:
            console.print(f"  Logs:     [cyan]{result.logs}[/cyan]")
        if not result.running:
            raise typer.Exit(3)  # like `systemctl status`: non-zero when not running

    for action, verb in (("start", "Start"), ("stop", "Stop")):
        _register_control(service_app, console, action, verb)


def _register_control(service_app: typer.Typer, console: Console, action: str, verb: str) -> None:
    @service_app.command(action, help=f"{verb} the installed service (root or an administrator).")
    def control(
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help="Workspace whose service (default: the default one)."),
        report: Optional[str] = typer.Option(None, "--report", hidden=True, help=_REPORT_HELP),
    ) -> None:
        log.info(f"hiro service {action}", workspace=workspace)
        from ..tools.service import ServiceStartTool, ServiceStopTool

        tool = ServiceStartTool if action == "start" else ServiceStopTool
        result = _run(console, action, report, lambda: tool().execute(workspace=workspace), _argv(action, workspace=workspace))
        pid = f" (PID {result['main_pid']})" if result.get("main_pid") else ""
        console.print(f"[green]{result['service']} {result['action']}:[/green] {result['state']}{pid}")
