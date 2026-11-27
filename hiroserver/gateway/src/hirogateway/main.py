"""hirogateway CLI entry point.

Thin wrappers around hirogateway.service — all real logic lives there.
The only code here is CLI plumbing (argument parsing, rich output) and
the foreground runner (_run_gateway / _serve) which is the actual asyncio
relay server and cannot be delegated to service.py.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path
from typing import Optional

import typer
import websockets
from hiro_channel_sdk import log_setup
from hiro_commons.log import Logger
from hiro_commons.process import is_running, read_pid, write_pid
from rich.console import Console
from rich.table import Table

from .auth import GatewayAuthManager
from .config import load_config, resolve_log_dir
from .constants import APP_NAME, PID_FILENAME
from .http_answers import answer_plain_http, install_quiet_handshakes
from .instance import (
    GatewayInstanceError,
    GatewayRegistry,
    load_registry,
    remove_instance,
    resolve_instance,
    set_default_instance,
)
from .relay import configure_auth, configure_instance_path, get_connected_devices, handle_connection
from .service import (
    GatewayInstanceStatusEntry,
    get_status,
    setup_instance,
    start_instance,
    stop_instance,
    teardown_instance,
)

cli = typer.Typer(
    name=APP_NAME,
    help="Hiro relay gateway with instance management.",
    add_completion=False,
    invoke_without_command=True,
)
instance_app = typer.Typer(help="Manage gateway instances.")
cli.add_typer(instance_app, name="instance")
console = Console()


@cli.callback(invoke_without_command=True)
def root(ctx: typer.Context) -> None:
    """Default command: start the default instance."""
    if ctx.invoked_subcommand is None:
        start()


# ---------------------------------------------------------------------------
# Foreground gateway runner (not part of service layer — this IS the server)
# ---------------------------------------------------------------------------


def _run_gateway(
    instance_name: str,
    *,
    verbose: bool,
    log_dir_override: str | None = None,
) -> None:
    """Load config for instance_name and run the relay server in the foreground."""
    try:
        entry, _ = resolve_instance(instance_name)
    except GatewayInstanceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    instance_path = Path(entry.path)
    config = load_config(instance_path)
    if log_dir_override:
        config.log_dir = log_dir_override
    _run_relay(
        entry.name,
        instance_path,
        host=entry.host,
        port=entry.port,
        desktop_public_key=config.desktop_public_key,
        log_dir=resolve_log_dir(instance_path, config),
        verbose=verbose,
    )


def _run_relay(
    name: str,
    instance_path: Path,
    *,
    host: str,
    port: int,
    desktop_public_key: str,
    log_dir: Path,
    verbose: bool,
) -> None:
    """Run the relay in the foreground: from a registry instance (`start`) or a folder its owner gives (`serve`)."""
    log_setup.init(
        "gateway",
        log_dir,
        level="DEBUG" if verbose else "INFO",
        foreground=True,
    )
    log = Logger.get("GATEWAY")
    auth_manager = GatewayAuthManager(desktop_public_key_b64=desktop_public_key)
    configure_auth(auth_manager)
    configure_instance_path(instance_path)
    log.info("✅ Gateway trust root configured", instance=name)
    log_setup.run(_serve(host, port))


async def _serve(host: str, port: int) -> None:
    log = Logger.get("GATEWAY")
    stop_event = asyncio.Event()

    def _shutdown(*_: object) -> None:
        log.info("🛑 Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _shutdown)
    else:
        # signal handlers on Windows run in the main thread outside the event
        # loop, so call_soon_threadsafe is required to safely set the asyncio
        # Event from there.
        signal.signal(signal.SIGTERM, lambda *_: loop.call_soon_threadsafe(stop_event.set))
        signal.signal(signal.SIGINT, lambda *_: loop.call_soon_threadsafe(stop_event.set))

    install_quiet_handshakes()
    async with websockets.serve(handle_connection, host, port, reuse_address=True, process_request=answer_plain_http):
        log.info(f"✅ Gateway listening at ws://{host}:{port}")
        await stop_event.wait()
        log.info("🛑 Shutting down", connected_devices=get_connected_devices())

    log.info("🛑 Gateway stopped")


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


@cli.command()
def start(
    instance: Optional[str] = typer.Option(
        None, "--instance", "-I", help="Gateway instance name (default: registry default)."
    ),
    log_dir: str = typer.Option(
        "",
        "--log-dir",
        help="Optional override log directory for this start only.",
    ),
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in foreground."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Start a configured gateway instance."""
    try:
        entry, _ = resolve_instance(instance)
    except GatewayInstanceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    instance_path = Path(entry.path)

    if foreground:
        # Child is sole PID writer — parent never writes, stop_process() cleans up.
        write_pid(instance_path, PID_FILENAME)
        console.print(
            "[green]Gateway starting[/green] in foreground "
            "[dim](Ctrl+C to stop)[/dim]"
        )
        try:
            _run_gateway(entry.name, verbose=verbose, log_dir_override=log_dir or None)
        except KeyboardInterrupt:
            pass
        console.print("[green]Gateway stopped.[/green]")
        return

    # Background mode: check already-running before spawning.
    pid = read_pid(instance_path, PID_FILENAME)
    if pid and is_running(pid):
        console.print(f"[yellow]Gateway already running[/yellow] (PID {pid}).")
        return

    try:
        result = start_instance(instance, verbose=verbose)
    except GatewayInstanceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if result.already_running:
        console.print(f"[yellow]Gateway already running[/yellow] (PID {result.pid}).")
    else:
        console.print(
            f"[green]Gateway started[/green] (PID {result.pid}). "
            f"WS: ws://{result.host}:{result.port}"
        )


@cli.command()
def serve(
    folder: Path = typer.Option(..., "--dir", help="Folder for the gateway's state file (its owner's choice)."),
    desktop_pubkey: str = typer.Option(..., "--desktop-pubkey", help="The desktop's Ed25519 public key (base64)."),
    port: int = typer.Option(..., "--port", "-p", help="Port to listen on."),
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="Address to listen on."),
    log_dir: str = typer.Option("", "--log-dir", help="Log folder (default: <dir>/logs)."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run a gateway in the foreground with no registry instance: how HiroServer runs its own beside it."""
    folder.mkdir(parents=True, exist_ok=True)
    try:
        _run_relay(
            "built-in",
            folder,
            host=host,
            port=port,
            desktop_public_key=desktop_pubkey,
            log_dir=Path(log_dir) if log_dir else folder / "logs",
            verbose=verbose,
        )
    except KeyboardInterrupt:
        pass


@cli.command()
def stop(
    instance: Optional[str] = typer.Option(
        None, "--instance", "-I", help="Gateway instance name (default: registry default)."
    ),
) -> None:
    """Stop a running gateway instance."""
    try:
        result = stop_instance(instance)
    except GatewayInstanceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if result.was_running:
        console.print(f"[green]Gateway stopped[/green] (was PID {result.pid}).")
    else:
        console.print("[yellow]Gateway is not running.[/yellow]")


@cli.command()
def status(
    instance: Optional[str] = typer.Option(
        None, "--instance", "-I", help="Gateway instance name (omit to show all instances)."
    ),
) -> None:
    """Show status for gateway instances."""
    try:
        result = get_status(instance)
    except GatewayInstanceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if not result.instances:
        console.print("[dim]No gateway instances configured.[/dim]")
        return

    registry = load_registry()
    for entry in result.instances:
        _print_instance_status(entry, registry)
        if len(result.instances) > 1:
            console.print()


@cli.command()
def teardown(
    instance: Optional[str] = typer.Option(
        None, "--instance", "-I", help="Gateway instance name (default: registry default)."
    ),
    purge: bool = typer.Option(
        False, "--purge", help="Also remove instance from registry and delete files."
    ),
    elevated_task: bool = typer.Option(
        False, "--elevated-task", help="(Windows) Request UAC for high-privilege task removal."
    ),
) -> None:
    """Stop gateway and remove auto-start registration for an instance."""
    try:
        result = teardown_instance(instance, purge=purge, elevated_task=elevated_task)
    except GatewayInstanceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if result.purged:
        console.print(f"[green]Gateway instance '{result.instance_name}' removed.[/green]")
    else:
        console.print("[green]Teardown complete.[/green]")


# ---------------------------------------------------------------------------
# Instance sub-commands
# ---------------------------------------------------------------------------


@instance_app.command("list")
def instance_list() -> None:
    """List configured gateway instances."""
    result = get_status()
    if not result.instances:
        console.print("[dim]No gateway instances configured.[/dim]")
        return

    table = Table(title="Gateway instances", show_header=True)
    table.add_column("", width=2, no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Bind")
    table.add_column("Path")

    for entry in result.instances:
        default_marker = "[cyan]*[/cyan]" if entry.is_default else ""
        status_text = "[green]running[/green]" if entry.running else "[dim]stopped[/dim]"
        table.add_row(default_marker, entry.name, status_text, f"{entry.host}:{entry.port}", entry.path)

    console.print(table)
    console.print("\n[cyan]*[/cyan] = default instance")


@instance_app.command("create")
def instance_create(
    name: str = typer.Argument(..., help="Gateway instance name."),
    desktop_pubkey: str = typer.Option(
        ...,
        "--desktop-pubkey",
        help="Desktop Ed25519 public key (base64). Mandatory at creation.",
    ),
    port: int = typer.Option(..., "--port", "-p", help="Gateway bind port."),
    host: str = typer.Option("0.0.0.0", "--host", "-H", help="Gateway bind host."),
    path: Optional[str] = typer.Option(None, "--path", help="Custom instance folder path."),
    log_dir: str = typer.Option("", "--log-dir", help="Custom log directory."),
    make_default: bool = typer.Option(False, "--set-default", help="Set as default instance."),
    skip_autostart: bool = typer.Option(
        False, "--skip-autostart", help="Do not register auto-start during create."
    ),
    elevated_task: bool = typer.Option(
        False, "--elevated-task", help="(Windows) Request UAC for high-privilege task creation."
    ),
) -> None:
    """Create a new gateway instance with mandatory values."""
    try:
        result = setup_instance(
            name,
            host=host,
            port=port,
            desktop_public_key=desktop_pubkey,
            path=Path(path) if path else None,
            log_dir=log_dir,
            make_default=make_default,
            skip_autostart=skip_autostart,
            elevated_task=elevated_task,
        )
    except GatewayInstanceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    console.print(f"[green]Gateway instance '[bold]{result.instance_name}[/bold]' created.[/green]")
    console.print(f"  path : [bold]{result.instance_path}[/bold]")
    console.print(f"  bind : [bold]{result.host}:{result.port}[/bold]")
    if make_default:
        console.print("  [cyan]Set as default instance.[/cyan]")
    if result.autostart_registered:
        console.print(f"  [green]Auto-start registered[/green] (method: {result.autostart_method}).")
    elif not skip_autostart:
        console.print(f"  [yellow]Auto-start registration failed[/yellow] ({result.autostart_method}).")
    console.print(f"\nNext: [bold]hirogate start --instance {result.instance_name}[/bold]")


@instance_app.command("set-default")
def instance_set_default(
    name: str = typer.Argument(..., help="Gateway instance name."),
) -> None:
    """Set default gateway instance."""
    try:
        set_default_instance(name)
    except GatewayInstanceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"[green]Default gateway instance set to '[bold]{name}[/bold]'.[/green]")


@instance_app.command("show")
def instance_show(
    name: Optional[str] = typer.Argument(None, help="Instance name (omit to show default)."),
) -> None:
    """Show details for a gateway instance."""
    # resolve_instance handles None -> env -> default, matching original semantics.
    try:
        entry, _ = resolve_instance(name)
    except GatewayInstanceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    result = get_status(entry.name)
    if not result.instances:
        console.print("[dim]No gateway instances found.[/dim]")
        return

    registry = load_registry()
    _print_instance_details(result.instances[0], registry)


@instance_app.command("remove")
def instance_remove(
    name: str = typer.Argument(..., help="Gateway instance name to remove."),
    purge: bool = typer.Option(
        False, "--purge", help="Also delete instance files from disk."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    elevated_task: bool = typer.Option(
        False, "--elevated-task", help="(Windows) Request UAC for high-privilege task removal."
    ),
) -> None:
    """Remove a gateway instance."""
    if not yes:
        action = "remove and delete files for" if purge else "remove"
        typer.confirm(f"Are you sure you want to {action} instance '{name}'?", abort=True)

    try:
        # teardown handles stop + autostart removal; remove_instance handles
        # registry cleanup (and optional file deletion when purge=True).
        teardown_instance(name, elevated_task=elevated_task)
        remove_instance(name, purge=purge)
    except GatewayInstanceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    console.print(f"[green]Gateway instance '[bold]{name}[/bold]' removed.[/green]")


# ---------------------------------------------------------------------------
# Rich output helpers
# ---------------------------------------------------------------------------


def _default_instance_name() -> str:
    """Return the default instance name from the registry."""
    registry = load_registry()
    return registry.default_instance


def _print_instance_status(entry: GatewayInstanceStatusEntry, registry: GatewayRegistry) -> None:
    title = f"hirogate status — {entry.name}"
    if entry.is_default:
        title += " [cyan](default)[/cyan]"

    table = Table(title=title, show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Gateway running", "[green]yes[/green]" if entry.running else "[red]no[/red]")
    table.add_row("PID", str(entry.pid) if entry.pid else "—")
    table.add_row("WebSocket URL", f"ws://{entry.host}:{entry.port}")
    table.add_row("Path", entry.path)
    console.print(table)


def _print_instance_details(entry: GatewayInstanceStatusEntry, registry: GatewayRegistry) -> None:
    instance_path = Path(entry.path)
    try:
        config = load_config(instance_path)
        log_dir = str(resolve_log_dir(instance_path, config))
    except Exception as exc:  # shown as unknown in the table
        Logger.get("GATEWAY").debug("The instance's log folder couldn't be read", instance=entry.name, error=str(exc))
        log_dir = "—"

    table = Table(
        title=f"Gateway instance: {entry.name}",
        show_header=False,
        box=None,
        padding=(0, 2),
    )
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Name", entry.name)
    table.add_row("Path", entry.path)
    table.add_row("Default", "[cyan]yes[/cyan]" if entry.is_default else "no")
    table.add_row(
        "Gateway",
        f"[green]running[/green] (PID {entry.pid})" if entry.running else "[dim]stopped[/dim]",
    )
    table.add_row("Bind", f"{entry.host}:{entry.port}")
    table.add_row("Log dir", log_dir)
    table.add_row("Desktop key", "[dim]configured in config.json[/dim]")
    console.print(table)


if __name__ == "__main__":
    cli()
