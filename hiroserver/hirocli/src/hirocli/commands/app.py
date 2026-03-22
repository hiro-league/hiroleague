"""CLI composition root: build app and wire command groups."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from .channel import register as register_channel_commands
from .device import register as register_device_commands
from .logs import register as register_logs_commands
from .metrics import register as register_metrics_commands
from .root import register as register_root_commands
from .workspace import register as register_workspace_commands

app = typer.Typer(
    name="hirocli",
    help="Hiro — desktop server CLI.",
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def _cli_init(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        return

    # Open routed log sinks (server.log + cli.log) for the default workspace
    # so CLI commands can write to cli.log via Logger.get("CLI.*").
    # Silently ignored when no workspace exists yet (e.g. first-ever run).
    try:
        from hiro_commons.log import Logger
        from ..domain.config import load_config, resolve_log_dir
        from ..domain.workspace import resolve_workspace

        entry, _ = resolve_workspace(None)
        config = load_config(Path(entry.path))
        Logger.set_level(config.log_level)
        Logger.setup(console=True)
        Logger.open_log_dir(resolve_log_dir(Path(entry.path), config))
    except Exception:
        pass


console = Console()

channel_app = typer.Typer(
    name="channel",
    help="Manage channel plugins (Telegram, WhatsApp, etc.).",
    add_completion=False,
)
device_app = typer.Typer(
    name="device",
    help="Manage paired device approvals.",
    add_completion=False,
)
logs_app = typer.Typer(
    name="logs",
    help="Search and tail server, channel, and gateway log files.",
    add_completion=False,
)
metrics_app = typer.Typer(
    name="metrics",
    help="View server resource metrics (CPU, memory, disk, network).",
    add_completion=False,
)
workspace_app = typer.Typer(
    name="workspace",
    help="Manage workspaces (isolated server instances).",
    add_completion=False,
)

app.add_typer(channel_app, name="channel")
app.add_typer(device_app, name="device")
app.add_typer(logs_app, name="logs")
app.add_typer(metrics_app, name="metrics")
app.add_typer(workspace_app, name="workspace")

register_root_commands(app, console)
register_channel_commands(channel_app, console)
register_device_commands(device_app, console)
register_logs_commands(logs_app, console)
register_metrics_commands(metrics_app, console)
register_workspace_commands(workspace_app, console)
