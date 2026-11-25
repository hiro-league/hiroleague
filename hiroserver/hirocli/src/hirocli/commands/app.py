"""CLI composition root: build app and wire command groups."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from .ai import register as register_ai_commands
from .voice import register as register_voice_commands
from .ai_plans import register as register_ai_plan_commands
from .channel import register as register_channel_commands
from .character import register as register_character_commands
from .device import register as register_device_commands
from .extension import register as register_extension_commands
from .logs import register as register_logs_commands
from .people import register as register_people_commands
from .knowledge import register as register_knowledge_commands
from ..domain.features import feature_active
from .metrics import register as register_metrics_commands
from .root import register as register_root_commands
from .catalog import register as register_catalog_commands
from .provider import register as register_provider_commands
from .provider import register_models_command
from .service import register as register_service_commands
from .sites import register as register_sites_commands
from .message import register as register_message_commands
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

    # The command's log: the default workspace's cli-<day>.jsonl (every line this `hiro` process logs), with the
    # safety nets. Before any workspace exists (the first run) the loggers still work, on the console only.
    from hiro_commons.log import Logger

    Logger.setup(console=True)
    try:
        from ..domain.config import load_config, resolve_log_dir
        from ..domain.workspace import resolve_workspace

        entry, _ = resolve_workspace(None)
        config = load_config(Path(entry.path))
        Logger.set_level(config.log_level)
        if config.module_log_levels:
            Logger.set_module_levels(config.module_log_levels)
        Logger.start(resolve_log_dir(Path(entry.path), config), name="cli", service="cli")
    except Exception as exc:
        Logger.get("CLI").debug("No workspace log for this command (no workspace yet?)", error=str(exc))


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
extension_app = typer.Typer(
    name="extension",
    help="Pair and manage extensions (programs such as HomeHiro that connect on their own).",
    add_completion=False,
)
ai_app = typer.Typer(
    name="ai",
    help="AI profiles: list, try, and which profile each extension use asks (Phase 7a).",
    add_completion=False,
)
voice_app = typer.Typer(
    name="voice",
    help="Voice profiles, Gemini's voices, voice uses and the spoken-clip cache (Phase 7b).",
    add_completion=False,
)
ai_uses_app = typer.Typer(
    name="uses",
    help="Extension AI uses and the profile each one asks.",
    add_completion=False,
)
ai_plan_app = typer.Typer(
    name="plan",
    help="Claude Code / Codex on your own plans: status, sign-in, sign-out, update, test.",
    add_completion=False,
)
ai_local_app = typer.Typer(
    name="local",
    help="Local model servers (LM Studio / Ollama): status and settings.",
    add_completion=False,
)
people_app = typer.Typer(
    name="people",
    help="The family list, its roles, and admin sign-ins.",
    add_completion=False,
)
character_app = typer.Typer(
    name="character",
    help="Manage characters (personas, prompts, photos).",
    add_completion=False,
)
logs_app = typer.Typer(
    name="logs",
    help="Read the logs of the core and of every app: search, tail, what went wrong (problems), one story by its id.",
    add_completion=False,
)
knowledge_app = typer.Typer(
    name="knowledge",
    help="Ingest and search workspace-local knowledge.",
    add_completion=False,
)
metrics_app = typer.Typer(
    name="metrics",
    help="View server resource metrics (CPU, memory, disk, network).",
    add_completion=False,
)
workspace_app = typer.Typer(
    name="workspaces",
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
sites_app = typer.Typer(
    name="sites",
    help="Every name this machine serves on the LAN: apps' names, extra names beside them, and other sites.",
    add_completion=False,
)
service_app = typer.Typer(
    name="service",
    help="Run the Hiro server as a system service: systemd, a Windows service or a Mac LaunchDaemon (starts at boot, restarts on failure).",
    add_completion=False,
)
message_app = typer.Typer(
    name="message",
    help="Send chat messages as the workspace owner (live server tools).",
    add_completion=False,
)

app.add_typer(channel_app, name="channel")
app.add_typer(character_app, name="character")
app.add_typer(device_app, name="device")
app.add_typer(extension_app, name="extension")
app.add_typer(people_app, name="people")
ai_app.add_typer(ai_uses_app, name="uses")
ai_app.add_typer(ai_plan_app, name="plan")
ai_app.add_typer(ai_local_app, name="local")
app.add_typer(ai_app, name="ai")
app.add_typer(voice_app, name="voice")
app.add_typer(logs_app, name="logs")
# Feature-gated: when Knowledge is hidden, its CLI group is neither mounted nor
# populated, so `hiro knowledge ...` doesn't exist (not in --help, not runnable).
if feature_active("knowledge"):
    app.add_typer(knowledge_app, name="knowledge")
# Feature-gated: when Metrics is hidden, `hiro metrics ...` is neither mounted nor populated.
if feature_active("metrics"):
    app.add_typer(metrics_app, name="metrics")
app.add_typer(workspace_app, name="workspaces")
app.add_typer(catalog_app, name="catalog")
app.add_typer(provider_app, name="provider")
app.add_typer(message_app, name="message")
app.add_typer(service_app, name="service")
app.add_typer(sites_app, name="sites")

register_root_commands(app, console)
register_models_command(app, console)
register_channel_commands(channel_app, console)
register_character_commands(character_app, console)
register_device_commands(device_app, console)
register_extension_commands(extension_app, console)
register_people_commands(people_app, console)
register_ai_commands(ai_app, ai_uses_app, console)
register_voice_commands(voice_app, console)
register_ai_plan_commands(ai_plan_app, ai_local_app, console)
register_logs_commands(logs_app, console)
if feature_active("knowledge"):
    register_knowledge_commands(knowledge_app, console)
if feature_active("metrics"):
    register_metrics_commands(metrics_app, console)
register_workspace_commands(workspace_app, console)
register_catalog_commands(catalog_app, console)
register_provider_commands(provider_app, console)
register_message_commands(message_app, console)
register_service_commands(service_app, console)
register_sites_commands(sites_app, console)
