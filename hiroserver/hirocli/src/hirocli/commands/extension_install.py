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
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import typer
from hiro_commons.log import Logger
from rich.console import Console

from ..domain.workspace import WorkspaceError

if TYPE_CHECKING:
    from ..domain.packages import Package

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

    # Fix: the job and the report sit in a folder of this person's, not in /tmp itself: Ubuntu keeps root from writing
    # a file another user made in a sticky folder (fs.protected_regular), so the report was refused (Simone, Nov 26)
    work = Path(tempfile.mkdtemp(prefix="hiro-app-"))
    job_path, report_path = str(work / "job.json"), str(work / "done.json")
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
        shutil.rmtree(work, ignore_errors=True)
    if payload.get("ok"):
        return payload["result"]
    raise _Stop(payload.get("error") or f"The administrator step ended (exit code {code}) and changed nothing it said.")


def _open(path: Path) -> Package:
    """The app's wheel the person named, with its libraries beside it; _Stop with the words when it isn't one."""
    from ..domain.packages import PackageRefused, open_package

    if not path.is_file():
        raise _Stop(f"There's no file at {path}.")
    try:
        return open_package(path)
    except PackageRefused as exc:
        raise _Stop(str(exc)) from exc


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
    found = _open(package)
    if not _core_running(workspace_path):
        raise _Stop("The core isn't running: start it first (`hiro start`, or its service), then install.")
    package_id = put_package_sync(workspace_path, found)
    sheet = _invoke(workspace_path, "extension_install_sheet", {"package": package_id, "workspace": workspace_id})
    if sheet["refused"]:
        raise _Stop(sheet["words"])
    print_sheet(console, sheet, all_optional=all_optional)
    _consent(console, approve)
    prepared = _invoke(workspace_path, "extension_install_prepare",
                       {"package": package_id, "all": all_optional, "in_advance": approve, "workspace": workspace_id})
    if prepared["refused"]:
        raise _Stop(prepared["words"])
    key = prepared["key"]
    log.info("hiro extension install: approved", key=key, approve=approve, all=all_optional)
    try:
        done = run_system_step(console, prepared["job"])
    except BaseException:
        # Declined, failed, or stopped (Ctrl-C): the core keeps the row only if its service was made (to remove it)
        _invoke(workspace_path, "extension_install_cancel", {"key": key, "workspace": workspace_id})
        raise
    console.print(f"[green]Made[/green] its account and service ({done['service']}).")
    console.print("Unpacking the app and starting it (a first install fetches its Python: a few minutes)…")
    finished = _invoke(workspace_path, "extension_install_finish", {"key": key, "workspace": workspace_id},
                       timeout=1800.0)
    if finished["refused"]:
        raise _Stop(f"{finished['words']}\nRemove it (`hiro extension remove {key}`), then install it again once "
                    "it is fixed.")
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


def _is_channel_name(text: str) -> bool:
    """A channel's name (``whatsapp``) rather than a file: no path in it, not a wheel's name."""
    return bool(text) and "/" not in text and "\\" not in text and not text.endswith(".whl") and not Path(text).exists()


def channel_step(console: Console, tool: str, name: str, params: dict[str, Any], workspace: str | None) -> bool:
    """Install, upgrade or remove a channel: in the running core (its program is the core's account's uv tool, and
    the core stops and starts the plugin around it), or here when the core is stopped. True when it was done."""
    from ..tools import extension_install as tools

    workspace_path, workspace_id = _workspace(workspace)
    params = {"channel_name": name, "workspace": workspace_id, **params}
    if _core_running(workspace_path):
        result = _invoke(workspace_path, tool, params, timeout=1800.0)
    else:
        found = next(t for t in (tools.ExtensionChannelInstallTool, tools.ExtensionChannelUpgradeTool,
                                 tools.ExtensionChannelRemoveTool) if t.name == tool)
        result = asdict(found().execute(**params))
    if result["refused"] and not result["gone"]:
        console.print(f"[red]{result['words']}[/red]")
        return False
    if tool == "extension_install_channel":
        console.print(f"[green]Installed[/green] [bold]{name} {result['version']}[/bold] ({result['package']}): it is "
                      f"off. Switch it on with `hiro channel enable {name}` or on the Extensions page.")
    elif tool == "extension_upgrade_channel":
        console.print(f"[green]Upgraded[/green] [bold]{name}[/bold]: {result['before'] or '?'} to "
                      f"{result['version'] or '?'}.")
    else:
        console.print(f"[green]Removed[/green] [bold]{name}[/bold]: {', '.join(result['gone'])}.")
    if result["words"]:
        console.print(f"[yellow]{result['words']}[/yellow]")
    return not result["refused"]


def register(extension_app: typer.Typer, console: Console) -> None:
    """Register the install commands on `hiro extension`."""
    import httpx

    @extension_app.command("install")
    def extension_install(
        package: str = typer.Argument(
            ..., help="An app's wheel (built by build-kit/package.py; its kits' wheels beside it), or a channel's "
                      "name (whatsapp)."
        ),
        approve: bool = typer.Option(
            False, "--approve", help="Approve what the app requires in advance, without asking (scripts, tests)."
        ),
        all_: bool = typer.Option(False, "--all", help="Approve its optional asks too."),
        version: str = typer.Option("", "--version", help="A channel: this version of its package on PyPI."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Install an app from its wheel (uv tool install, as the core is): shows what it asks and asks you to approve
        it, makes its account and service (one administrator step), then the core installs it, starts it and it pairs
        by itself. Or install a channel by its name: its program as a uv tool, switched off until you switch it on."""
        log.info("hiro extension install", package=Path(package).name, approve=approve, all=all_, version=version)
        ok = True
        try:
            if _is_channel_name(package):
                ok = channel_step(console, "extension_install_channel", package, {"version": version}, workspace)
            else:
                install(console, Path(package).resolve(), approve=approve, all_optional=all_, workspace=workspace)
        except _Stop as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        except (WorkspaceError, RuntimeError, OSError, httpx.HTTPError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        if not ok:  # typer's Exit is a RuntimeError: raised outside the try, or it is printed as "1"
            raise typer.Exit(1)

    @extension_app.command("upgrade")
    def extension_upgrade(
        key: str = typer.Argument(..., help="The installed app's key, or a channel's name (see `hiro extension list`)."),
        package: Optional[Path] = typer.Argument(
            None, help="An app: its newer wheel (built by build-kit/package.py; its kits' wheels beside it)."
        ),
        allow_row_loss: Optional[list[str]] = typer.Option(
            None, "--allow-row-loss", help="A table the new version's migrations may empty; repeat it."
        ),
        version: str = typer.Option("", "--version", help="A channel: this version of its package on PyPI."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Upgrade an app the core installed: its data is copied and the new migrations tried on a copy first; then it
        switches, and goes back by itself (data and version) when the new version doesn't answer. Or upgrade a
        channel: its program installed again from where it came from (or --version from PyPI), then started again."""
        log.info("hiro extension upgrade", key=key, package=package.name if package else "", version=version,
                 allow_row_loss=allow_row_loss)
        try:
            if package is None:
                ok = channel_step(console, "extension_upgrade_channel", key, {"version": version}, workspace)
            else:
                ok = upgrade(console, key, package.resolve(), allow_row_loss=allow_row_loss or [],
                             workspace=workspace)
        except (_Stop, WorkspaceError, RuntimeError, OSError, httpx.HTTPError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        if not ok:
            raise typer.Exit(1)

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


def upgrade(console: Console, key: str, package: Path, *, allow_row_loss: list[str], workspace: str | None) -> bool:
    """Hand the package to the core and run the upgrade there; True when it runs the new version."""
    from ..domain.workspace_server_client import put_package_sync

    workspace_path, workspace_id = _workspace(workspace)
    found = _open(package)
    if not _core_running(workspace_path):
        raise _Stop("The core isn't running: it upgrades its apps itself.")
    package_id = put_package_sync(workspace_path, found)
    console.print("Upgrading: its data copied and its migrations tried first, then switched and checked…")
    done = _invoke(workspace_path, "extension_upgrade",
                   {"key": key, "package": package_id, "allow_row_loss": allow_row_loss, "workspace": workspace_id},
                   timeout=3600.0)
    colour = {"upgraded": "green", "stayed": "yellow"}.get(done["outcome"], "red")
    console.print(f"[{colour}]{done['words']}[/{colour}]")
    if done["new_asks"]:
        console.print("It asks for more, which waits for your yes on the Extensions page (or `hiro extension approve`):")
        for words in done["new_asks"]:
            console.print(f"  • {words}")
    return done["outcome"] == "upgraded"
