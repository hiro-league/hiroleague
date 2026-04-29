"""CLI composition root: build app and wire command groups."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from .channel import register as register_channel_commands
from .character import register as register_character_commands
from .device import register as register_device_commands
from .logs import register as register_logs_commands
from .metrics import register as register_metrics_commands
from .root import register as register_root_commands
from .catalog import register as register_catalog_commands
from .provider import register as register_provider_commands
from .provider import register_models_command
from .workspace import register as register_workspace_commands

app = typer.Typer(
    name="hiro",
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
character_app = typer.Typer(
    name="character",
    help="Manage characters (personas, prompts, photos).",
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
catalog_app = typer.Typer(
    name="catalog",
    help="Browse the bundled LLM provider and model catalog.",
    add_completion=False,
)
provider_app = typer.Typer(
    name="provider",
    help="Manage workspace provider credentials (API keys, local endpoints).",
    add_completion=False,
)

app.add_typer(channel_app, name="channel")
app.add_typer(character_app, name="character")
app.add_typer(device_app, name="device")
app.add_typer(logs_app, name="logs")
app.add_typer(metrics_app, name="metrics")
app.add_typer(workspace_app, name="workspace")
app.add_typer(catalog_app, name="catalog")
app.add_typer(provider_app, name="provider")

register_root_commands(app, console)
register_models_command(app, console)
register_channel_commands(channel_app, console)
register_character_commands(character_app, console)
register_device_commands(device_app, console)
register_logs_commands(logs_app, console)
register_metrics_commands(metrics_app, console)
register_workspace_commands(workspace_app, console)
register_catalog_commands(catalog_app, console)
register_provider_commands(provider_app, console)
