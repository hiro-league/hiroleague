"""Entry point for the detached server process spawned by `hirocli start`.

Runs the FastAPI HTTP server and ChannelManager concurrently inside a single
asyncio event loop.  Gateway connectivity is owned by the mandatory
`devices` channel plugin.

This module is a **composition root** — it creates a ServerContext, calls
factory functions owned by each subsystem, wires the components together,
and starts the event loop.  No business logic or provider maps live here.

Workspace path resolution:
  - Foreground mode: workspace_path is passed directly by tools/server.py.
  - Background mode: workspace_path is read from the HIRO_WORKSPACE_PATH env var
    set by tools/server.py before Popen.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

from hiro_commons.log import Logger
from hiro_commons.process import remove_pid, spawn_detached, uv_python_cmd, write_pid

from hirocli.constants import ENV_ADMIN_UI, ENV_METRICS, ENV_WORKSPACE, ENV_WORKSPACE_PATH, PID_FILENAME
from hirocli.domain.config import load_config, mark_disconnected
from hirocli.domain.crypto import load_or_create_master_key
from hirocli.domain.data_store import ensure_data_db
from hirocli.domain.db import ensure_db
from hirocli.runtime.channel_event_handler import ChannelEventHandler
from hirocli.runtime.channel_manager import ChannelManager
from hirocli.runtime.communication_manager import CommunicationManager
from hirocli.runtime.event_handler import EventHandler
from hirocli.runtime.http_server import app as http_app, run_http_server
from hirocli.runtime.infra_event_handlers import InfraEventHandlers
from hirocli.runtime.message_adapter import create_adapter_pipeline
from hirocli.runtime.request_handler import RequestHandler
from hirocli.runtime.server_context import ServerContext
from hirocli.services.metrics import MetricsCollector
from hirocli.services.tts import create_tts_service
from hirocli.tools import all_tools
from hirocli.tools.registry import ToolRegistry

log = Logger.get("SERVER")


# ---------------------------------------------------------------------------
# Composition root
# ---------------------------------------------------------------------------


def _build_context(
    workspace_path: Path,
    workspace_name: str,
    stop_event: asyncio.Event,
) -> ServerContext:
    """Load config, keys, and build the shared ServerContext."""
    config = load_config(workspace_path)
    desktop_private_key = load_or_create_master_key(workspace_path, filename=config.master_key_file)
    return ServerContext(
        workspace_path=workspace_path,
        workspace_name=workspace_name,
        config=config,
        stop_event=stop_event,
        desktop_private_key=desktop_private_key,
    )


def _wire_communication_stack(ctx: ServerContext):
    """Create the adapter pipeline, event handler, CommunicationManager, and RequestHandler."""
    adapter_pipeline = create_adapter_pipeline(ctx.workspace_path)
    event_handler = EventHandler()
    comm_manager = CommunicationManager(
        ctx=ctx,
        adapter_pipeline=adapter_pipeline,
        event_handler=event_handler,
    )
    request_handler = RequestHandler(ctx, comm_manager)

    from hirocli.runtime.request_methods import register_request_methods
    register_request_methods(request_handler)

    comm_manager.set_request_handler(request_handler)
    return comm_manager


def _wire_channel_stack(ctx: ServerContext, comm_manager: CommunicationManager):
    """Create infra handlers, channel event handler, and ChannelManager."""
    infra_handlers = InfraEventHandlers(ctx)
    channel_event_handler = ChannelEventHandler()
    infra_handlers.register_all(channel_event_handler)
    log.info("Registered special channel event handlers")

    channel_manager = ChannelManager(
        ctx,
        on_message=comm_manager.receive,
        on_event=channel_event_handler.handle,
    )
    # Setter injection: InfraEventHandlers needs ChannelManager for pairing
    # responses, and CommunicationManager needs it for outbound delivery.
    # Both are constructed before ChannelManager exists.
    infra_handlers.set_channel_manager(channel_manager)
    comm_manager.set_channel_manager(channel_manager)
    return channel_manager


def _register_signal_handlers(stop_event: asyncio.Event) -> None:
    """Wire OS signals to trigger graceful shutdown."""
    def _on_signal(*_: object) -> None:
        log.info("Shutdown signal received")
        stop_event.set()

    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, _on_signal)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def _main(
    foreground: bool = False,
    workspace_path: Path | None = None,
    workspace_name: str | None = None,
    admin: bool = False,
    metrics: bool = False,
) -> None:
    if workspace_path is None:
        ws_str = os.environ.get(ENV_WORKSPACE_PATH)
        if not ws_str:
            raise RuntimeError(
                "HIRO_WORKSPACE_PATH environment variable is not set. "
                "The server process must be started via 'hirocli start'."
            )
        workspace_path = Path(ws_str)
    if workspace_name is None:
        workspace_name = os.environ.get(ENV_WORKSPACE) or workspace_path.name

    # --- Build context ---
    stop_event = asyncio.Event()
    ctx = _build_context(workspace_path, workspace_name, stop_event)

    Logger.set_level(ctx.config.log_level)
    Logger.setup(console=foreground)
    Logger.open_log_dir(ctx.log_dir)
    if ctx.config.module_log_levels:
        Logger.set_module_levels(ctx.config.module_log_levels)

    log.info("🚀 Hiro Server starting...", workspace=workspace_name, foreground=foreground, admin=admin)
    log.info(
        f"✅ Loaded workspace '{workspace_name}' config",
        http_port=ctx.config.http_port,
        plugin_port=ctx.config.plugin_port,
        admin_port=ctx.config.admin_port,
        gateway_url=ctx.config.gateway_url,
        log_dir=str(ctx.log_dir),
    )

    write_pid(workspace_path, PID_FILENAME)
    ensure_db(workspace_path)
    ensure_data_db(workspace_path)

    # --- Wire HTTP + tools ---
    http_app.state.ctx = ctx
    tool_registry = ToolRegistry()
    tool_registry.register_all(all_tools())
    http_app.state.tool_registry = tool_registry
    log.info(f"✅ Loaded Tool Definitions: ({len(tool_registry._tools)})")

    # --- Metrics ---
    effective_metrics = ctx.config.metrics_enabled or metrics or os.environ.get(ENV_METRICS) == "1"
    metrics_collector = MetricsCollector(
        enabled=effective_metrics,
        interval=ctx.config.metrics_interval,
        history_size=ctx.config.metrics_history_size,
    )
    http_app.state.metrics_collector = metrics_collector
    log.info("Metrics collector configured", enabled=effective_metrics, interval=ctx.config.metrics_interval)

    # --- Wire communication + channel stacks ---
    comm_manager = _wire_communication_stack(ctx)
    channel_manager = _wire_channel_stack(ctx, comm_manager)
    http_app.state.channel_info_provider = channel_manager.get_channel_info
    metrics_collector.set_child_pid_provider(channel_manager.get_child_processes)

    # --- Wire agent ---
    from hirocli.runtime.agent_manager import AgentManager

    log.info("🕒 Loading Text-to-Speech services")
    tts_service = create_tts_service(workspace_path)
    agent_manager = AgentManager(ctx, comm_manager, tts_service=tts_service)

    _register_signal_handlers(stop_event)

    log.info(
        "Server ready — launching components",
        workspace=str(workspace_path),
        http=f"http://{ctx.config.http_host}:{ctx.config.http_port}/status",
        plugin_ws=f"ws://127.0.0.1:{ctx.config.plugin_port}",
        device_id=ctx.config.device_id,
    )

    # --- Launch all coroutines ---
    coros = [
        run_http_server(ctx),
        channel_manager.run(),
        comm_manager.run(),
        agent_manager.run(),
        metrics_collector.run(),
    ]
    if admin:
        from hirocli.ui.run import run_admin_ui

        coros.append(run_admin_ui(ctx))

    server_task = asyncio.ensure_future(
        asyncio.gather(*coros, return_exceptions=True)
    )

    await stop_event.wait()
    await asyncio.sleep(1.5)
    server_task.cancel()
    try:
        await server_task
    except (asyncio.CancelledError, Exception):
        pass

    if ctx.restart_requested:
        log.info("Restart requested — spawning new server process")
        _spawn_server(workspace_path, admin=ctx.restart_admin)

    mark_disconnected(workspace_path)
    log.info("hirocli server exited")


def _spawn_server(workspace_path: Path, admin: bool = False) -> None:
    """Spawn a new detached server process (used for self-restart).

    Uses spawn_detached from hiro_commons; the new child writes its own PID
    via write_pid() at startup, so we don't write it here.
    """
    script = str(Path(__file__))
    env = {**os.environ, ENV_WORKSPACE_PATH: str(workspace_path)}
    if admin:
        env[ENV_ADMIN_UI] = "1"
    elif ENV_ADMIN_UI in env:
        del env[ENV_ADMIN_UI]

    remove_pid(workspace_path, PID_FILENAME)

    stderr_log = workspace_path / "stderr.log"
    spawn_detached([*uv_python_cmd(), script], env=env, stderr_log=stderr_log)
    log.info("New server process spawning (child will write its own PID)")


if __name__ == "__main__":
    _admin = os.environ.get(ENV_ADMIN_UI) == "1"
    _metrics = os.environ.get(ENV_METRICS) == "1"
    _ws_name = os.environ.get(ENV_WORKSPACE) or None
    asyncio.run(_main(workspace_name=_ws_name, admin=_admin, metrics=_metrics))
