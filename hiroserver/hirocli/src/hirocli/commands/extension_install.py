"""`hiro extension install`, `start`, `stop` and the elevated `system` step (Installing apps, phase 5).

An install asks the person first. It shows what the app asks to do, in the Extensions page's words, and asks
"Approve these?" before anything is made. A "no" changes nothing. `--approve` gives that yes in advance (scripts,
tests), and the lines are still printed and kept in the install's story. Then comes the one administrator step the
system asks for (sudo, or Windows' prompt), which makes the app's account and service. Then the running core unpacks
the app and starts it, and the app pairs by itself. Removing is `hiro extension remove` (commands/extension.py).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

import typer
from hiro_commons.log import Logger
from rich.console import Console

from ..domain.workspace import WorkspaceError

log = Logger.get("CLI.EXTENSION")

_WORKSPACE_HELP = "Workspace name (default: registry default)."
_PAIR_WAIT_S = 90


class _Stop(Exception):
    """Stop the command with these words (already logged where it matters)."""


def _workspace(workspace: str | None) -> tuple[Path, str]:
    from ..domain.workspace import resolve_workspace

    entry, _ = resolve_workspace(workspace)
    return Path(entry.path), entry.id


def _core_running(workspace_path: Path) -> bool:
    from hiro_commons.process import is_running, read_pid

    from ..constants import PID_FILENAME

    return is_running(read_pid(workspace_path, PID_FILENAME))


def _invoke(workspace_path: Path, tool: str, params: dict[str, Any], *, timeout: float = 120.0) -> dict[str, Any]:
    from ..domain.workspace_server_client import post_invoke_sync

    return post_invoke_sync(workspace_path, tool, params, timeout_seconds=timeout)


def print_sheet(console: Console, sheet: dict[str, Any], *, all_optional: bool) -> None:
    """What the app asks, as the person approves it: required first, then the optional ones."""
    console.print(f"[bold]{sheet['title']} {sheet['version']}[/bold] ([cyan]{sheet['key']}[/cyan], port "
                  f"{sheet['port']}) asks to:")
    for item in sheet["items"]:
        if not item["required"]:
            continue
        subject = f" [dim]({item['subject']})[/dim]" if item["subject"] else ""
        why = f" [dim]— {item['why']}[/dim]" if item["why"] else ""
        if item["understood"]:
            console.print(f"  • {item['words']}{subject}{why}")
        else:
            console.print(f"  • [yellow]{item['permission']}: not understood by this core, never approved[/yellow]")
    optional = [i for i in sheet["items"] if not i["required"] and i["understood"]]
    if optional:
        head = "Optional, approved too (--all):" if all_optional else \
            "Optional, not approved now (--all approves them; or later, on the Extensions page):"
        console.print(head)
        for item in optional:
            why = f" [dim]— {item['why']}[/dim]" if item["why"] else ""
            console.print(f"  • {item['words']}{why}")


def _consent(console: Console, approve: bool) -> None:
    """The person's yes, or _Stop. Never a yes by default: with no terminal to ask, only --approve says it."""
    if approve:
        console.print("[green]Approved in advance (--approve).[/green]")
        return
    if not sys.stdin.isatty():
        raise _Stop("No one to ask here: run it in a terminal, or pass --approve to approve these in advance.")
    if not typer.confirm("Approve these?", default=False):
        raise _Stop("Not approved: nothing was changed.")


def run_system_step(console: Console, job: dict[str, Any]) -> dict[str, Any]:
    """The one administrator step, `hiro extension system <job>`: sudo on Linux and Mac (the terminal asks for the
    password), Windows' prompt otherwise. Returns what it did; _Stop when it was declined or failed."""
    from hiro_commons.systemd_service import ServiceError

    from ..linux_service import hiro_executable

    fd, job_path = tempfile.mkstemp(prefix="hiro-app-job-", suffix=".json")
    os.close(fd)
    report_fd, report_path = tempfile.mkstemp(prefix="hiro-app-done-", suffix=".json")
    os.close(report_fd)
    try:
        Path(job_path).write_text(json.dumps(job), encoding="utf-8")
        args = [hiro_executable(), "extension", "system", job_path, "--report", report_path]
        if sys.platform == "win32":
            from hiro_commons.winsw_service import ElevationRefused, is_admin, run_elevated

            console.print("[yellow]This makes an account and a service:[/yellow] Windows will ask (one prompt).")
            try:
                code = subprocess.run(args, check=False).returncode if is_admin() else run_elevated(args)  # noqa: S603
            except ElevationRefused as exc:
                raise _Stop(str(exc)) from exc
            except ServiceError as exc:
                raise _Stop(str(exc)) from exc
        else:
            console.print("[yellow]This makes an account and a service:[/yellow] sudo asks for your password.")
            command = args if os.geteuid() == 0 else ["sudo", *args]
            code = subprocess.run(command, check=False).returncode  # noqa: S603 — this program, a fixed job file
        try:
            payload = json.loads(Path(report_path).read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            payload = {}
    finally:
        Path(job_path).unlink(missing_ok=True)
        Path(report_path).unlink(missing_ok=True)
    if payload.get("ok"):
        return payload["result"]
    raise _Stop(payload.get("error") or f"The administrator step ended (exit code {code}) and changed nothing it said.")


def _wait_paired(workspace_path: Path, workspace_id: str, key: str) -> dict[str, Any] | None:
    deadline = time.monotonic() + _PAIR_WAIT_S
    while time.monotonic() < deadline:
        rows = _invoke(workspace_path, "extension_installs", {"workspace": workspace_id})["installs"]
        row = next((r for r in rows if r["key"] == key), None)
        if row is None or row["state"] not in ("waiting",):
            return row
        time.sleep(2)
    return None


def install(console: Console, package: Path, *, approve: bool, all_optional: bool, workspace: str | None) -> None:
    from ..domain.workspace_server_client import put_package_sync

    workspace_path, workspace_id = _workspace(workspace)
    if not package.is_file():
        raise _Stop(f"There's no file at {package}.")
    if not _core_running(workspace_path):
        raise _Stop("The core isn't running: start it first (`hiro start`, or its service), then install.")
    package_id = put_package_sync(workspace_path, package)
    sheet = _invoke(workspace_path, "extension_install_sheet", {"package": package_id, "workspace": workspace_id})
    if sheet["refused"]:
        raise _Stop(sheet["words"])
    print_sheet(console, sheet, all_optional=all_optional)
    _consent(console, approve)
    prepared = _invoke(workspace_path, "extension_install_prepare",
                       {"package": package_id, "all": all_optional, "workspace": workspace_id})
    if prepared["refused"]:
        raise _Stop(prepared["words"])
    key = prepared["key"]
    log.info("hiro extension install: approved", key=key, approve=approve, all=all_optional)
    try:
        done = run_system_step(console, prepared["job"])
    except _Stop:
        _invoke(workspace_path, "extension_install_cancel", {"key": key, "workspace": workspace_id})
        raise
    console.print(f"[green]Made[/green] its account and service ({done['service']}).")
    console.print("Unpacking the app and starting it (a first install fetches its Python: a few minutes)…")
    finished = _invoke(workspace_path, "extension_install_finish", {"key": key, "workspace": workspace_id},
                       timeout=1800.0)
    if finished["refused"]:
        raise _Stop(f"{finished['words']}\nTry again with `hiro extension install` once it is fixed, or remove it: "
                    f"`hiro extension remove {key}`.")
    row = _wait_paired(workspace_path, workspace_id, key)
    if row is None or row["state"] != "running":
        console.print(f"[yellow]{sheet['title']} runs but hasn't paired yet.[/yellow] See its log in "
                      f"{row['data'] if row else 'its data folder'}, and `hiro extension list`.")
        return
    console.print(f"[green]Installed[/green] [bold]{sheet['title']} {sheet['version']}[/bold]: it runs and is paired.")
    address = next((i["subject"] for i in sheet["items"] if i["permission"] == "site.address"), "")
    if address:
        console.print(f"Open it at [bold]{address}[/bold]. Its data: {row['data']}")


def remove_installed(console: Console, workspace_path: Path, workspace_id: str, key: str, *, purge: bool) -> None:
    """Remove an app the core installed: the administrator step first (its service, the core's right on it, its
    account; with purge its folder and data), then the core forgets it (record, names, grants, picks, releases)."""
    from ..tools.extension_install import ExtensionInstallForgetTool

    done = run_system_step(console, {"action": "remove", "key": key, "purge": purge})
    console.print(f"[green]Removed[/green] its service and account ({done['service']}).")
    params = {"key": key, "workspace": workspace_id}
    if _core_running(workspace_path):
        result = _invoke(workspace_path, "extension_install_forget", params)
    else:
        result = asdict(ExtensionInstallForgetTool().execute(**params))
    removed = result.get("removed") or {}
    if removed.get("site_name"):
        console.print(f"Its name {removed['site_name']} is free again.")
    if purge:
        console.print("Its folder and its data are gone.")
    else:
        console.print(f"[dim]Its data stays in {done['folder']}; `--purge` removes it too.[/dim]")


def register(extension_app: typer.Typer, console: Console) -> None:
    """Register the install commands on `hiro extension`."""
    import httpx

    @extension_app.command("install")
    def extension_install(
        package: Path = typer.Argument(..., help="The app's package (a .zip built by build-kit/package.py)."),
        approve: bool = typer.Option(
            False, "--approve", help="Approve what the app requires in advance, without asking (scripts, tests)."
        ),
        all_: bool = typer.Option(False, "--all", help="Approve its optional asks too."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Install an app from its package: shows what it asks and asks you to approve it, makes its account and
        service (one administrator step), then the core unpacks it, starts it and it pairs by itself."""
        log.info("hiro extension install", package=package.name, approve=approve, all=all_)
        try:
            install(console, package.resolve(), approve=approve, all_optional=all_, workspace=workspace)
        except _Stop as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        except (WorkspaceError, RuntimeError, OSError, httpx.HTTPError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc

    def _service(key: str, workspace: str | None, tool: str) -> None:
        try:
            workspace_path, workspace_id = _workspace(workspace)
            if not _core_running(workspace_path):
                raise _Stop("The core isn't running: it starts and stops its apps itself.")
            result = _invoke(workspace_path, tool, {"key": key, "workspace": workspace_id})
        except (_Stop, WorkspaceError, RuntimeError, OSError, httpx.HTTPError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        if result["refused"]:
            console.print(f"[red]{result['words']}[/red]")
            raise typer.Exit(1)
        console.print(f"[green]{key} {result['step']}.[/green]")

    @extension_app.command("start")
    def extension_start(
        key: str = typer.Argument(..., help="The installed app's key (see `hiro extension list`)."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Start an app the core installed."""
        _service(key, workspace, "extension_start")

    @extension_app.command("stop")
    def extension_stop(
        key: str = typer.Argument(..., help="The installed app's key (see `hiro extension list`)."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Stop an app the core installed."""
        _service(key, workspace, "extension_stop")

    @extension_app.command("system", hidden=True)
    def extension_system(
        job_file: Path = typer.Argument(..., help="The job the core answered (install or remove one app)."),
        report: Optional[str] = typer.Option(None, "--report", help="Where to write what was done (JSON)."),
    ) -> None:
        """The administrator step of an install or a removal (run by `hiro extension install` / `remove` through sudo
        or Windows' prompt): an app's account and service, and the core's right to start and stop it."""
        from hiro_commons.systemd_service import ServiceError

        from .. import app_system
        from ..domain.hiro_home import hiro_home
        from ..domain.system_job import JobRefused, SystemJob, check_job

        def _report(payload: dict[str, Any]) -> None:
            if report:
                Path(report).write_text(json.dumps(payload), encoding="utf-8")

        try:
            job = SystemJob.model_validate_json(job_file.read_text(encoding="utf-8"))
            app = check_job(job, hiro_home())  # its own Hiro home, never one from the job
            log.info("hiro extension system", action=job.action, key=job.key, purge=job.purge)
            done = app_system.apply(app, job.action, purge=job.purge)
        except (JobRefused, ServiceError, OSError, ValueError) as exc:
            _report({"ok": False, "error": str(exc)})
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        except Exception as exc:
            # Windows' elevated window closes when it ends: whatever went wrong must reach the terminal that asked
            log.error("❌ The administrator step of an app failed — HiroServer · extension", exc_info=True)
            _report({"ok": False, "error": f"Something went wrong ({type(exc).__name__}); see the CLI's log."})
            raise typer.Exit(1) from exc
        _report({"ok": True, "result": asdict(done)})
        console.print(f"[green]Done:[/green] {done.action} {done.key} ({done.service}).")
