"""Entry point for the detached server process spawned by `hirocli start`.

Runs the FastAPI HTTP server and ChannelManager concurrently inside a single
asyncio event loop.  Gateway connectivity is owned by the mandatory
`devices` channel plugin.

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
from hirocli.domain.config import Config, load_config, mark_disconnected, resolve_log_dir
from hirocli.domain.crypto import load_or_create_master_key
from hirocli.domain.db import ensure_db
from hirocli.runtime.agent_manager import AgentManager
from hirocli.runtime.channel_event_handler import ChannelEventHandler
from hirocli.runtime.channel_manager import ChannelManager
from hirocli.runtime.communication_manager import CommunicationManager
from hirocli.runtime.event_handler import EventHandler
from hirocli.runtime.http_server import app as http_app, run_http_server
from hirocli.runtime.infra_event_handlers import InfraEventHandlers
from hirocli.runtime.message_adapter import MessageAdapterPipeline
from hirocli.runtime.request_handler import RequestHandler
from hirocli.runtime.adapters.audio_adapter import AudioTranscriptionAdapter
from hirocli.runtime.adapters.image_adapter import ImageUnderstandingAdapter
from hirocli.services.metrics import MetricsCollector
from hirocli.services.stt import GeminiSTTProvider, OpenAISTTProvider, STTService
from hirocli.services.vision_service import VisionService
from hirocli.tools import all_tools
from hirocli.tools.registry import ToolRegistry

log = Logger.get("SERVER")


# ---------------------------------------------------------------------------
# Setup helpers — each creates one logical subsystem and returns it.
# ---------------------------------------------------------------------------


def _create_adapter_pipeline() -> MessageAdapterPipeline:
    """Create the media services and message adapter pipeline."""
    log.info("🕒 Loading Media Services")
    log.info("➡️ Loading Speech to Text Services")
    stt_service = STTService(providers=[
        OpenAISTTProvider(),
        GeminiSTTProvider(),
    ])
    log.info("➡️ Loading Vision Services")
    vision_service = VisionService()

    pipeline = MessageAdapterPipeline([
        AudioTranscriptionAdapter(service=stt_service),
        ImageUnderstandingAdapter(service=vision_service),
    ])
    log.info("✅ Adapter pipeline ready", adapters=["audio_transcription", "image_understanding"])
    return pipeline


def _create_communication_stack(
    adapter_pipeline: MessageAdapterPipeline,
    workspace_path: Path,
) -> CommunicationManager:
    """Create the EventHandler, CommunicationManager, and RequestHandler."""
    event_handler = EventHandler()
    comm_manager = CommunicationManager(
        adapter_pipeline=adapter_pipeline,
        event_handler=event_handler,
        workspace_path=workspace_path,
    )
    request_handler = RequestHandler(comm_manager, workspace_path)
    comm_manager.set_request_handler(request_handler)
    return comm_manager


def _create_channel_stack(
    config: Config,
    workspace_path: Path,
    stop_event: asyncio.Event,
    desktop_private_key: object,
    comm_manager: CommunicationManager,
) -> ChannelManager:
    """Create infra handlers, channel event handler, and channel manager."""
    infra_handlers = InfraEventHandlers(workspace_path, config, desktop_private_key)
    channel_event_handler = ChannelEventHandler()
    infra_handlers.register_all(channel_event_handler)
    log.info("✅ Registered special channel event handlers")

    channel_manager = ChannelManager(
        config,
        workspace_path,
        stop_event,
        on_message=comm_manager.receive,
        on_event=channel_event_handler.handle,
    )
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


def _log_agent_config(workspace_path: Path) -> None:
    """Best-effort log of the agent model configuration."""
    try:
        from hirocli.domain.agent_config import load_agent_config
        cfg = load_agent_config(workspace_path)
        log.info(
            "✅ AI Agent config loaded",
            model=cfg.model,
            provider=cfg.provider,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
        )
    except Exception:
        log.info("AI Agent config loaded (using defaults)")


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

    config = load_config(workspace_path)
    log_dir = resolve_log_dir(workspace_path, config)

    Logger.set_level(config.log_level)
    Logger.setup(console=foreground)
    Logger.open_log_dir(log_dir)
    # Third-party WARNING+ is captured automatically by the catch-all
    # bridge installed in Logger.setup().  No per-library silence_stdlib
    # calls needed.
    if config.module_log_levels:
        Logger.set_module_levels(config.module_log_levels)
    log.info("🚀 Hiro Server starting...", workspace=workspace_name, foreground=foreground, admin=admin)
    log.info(
        f"✅ Loaded workspace '{workspace_name}' config",
        http_port=config.http_port,
        plugin_port=config.plugin_port,
        admin_port=config.admin_port,
        gateway_url=config.gateway_url,
        log_dir=str(log_dir),
    )

    desktop_private_key = load_or_create_master_key(workspace_path, filename=config.master_key_file)
    stop_event = asyncio.Event()
    http_app.state.stop_event = stop_event
    write_pid(workspace_path, PID_FILENAME)
    ensure_db(workspace_path)
    http_app.state.workspace_path = workspace_path

    tool_registry = ToolRegistry()
    tool_registry.register_all(all_tools())
    http_app.state.tool_registry = tool_registry
    log.info(f"✅ Loaded Tool Definitions: ({len(tool_registry._tools)})")

    # --metrics flag (via env var or direct param) overrides config for this run
    effective_metrics = config.metrics_enabled or metrics or os.environ.get(ENV_METRICS) == "1"
    metrics_collector = MetricsCollector(
        enabled=effective_metrics,
        interval=config.metrics_interval,
        history_size=config.metrics_history_size,
    )
    http_app.state.metrics_collector = metrics_collector
    log.info(
        "Metrics collector configured",
        enabled=effective_metrics,
        interval=config.metrics_interval,
    )

    adapter_pipeline = _create_adapter_pipeline()
    comm_manager = _create_communication_stack(adapter_pipeline, workspace_path)
    channel_manager = _create_channel_stack(
        config, workspace_path, stop_event, desktop_private_key, comm_manager,
    )
    http_app.state.channel_info_provider = channel_manager.get_channel_info
    metrics_collector.set_child_pid_provider(channel_manager.get_child_processes)

    agent_manager = AgentManager(comm_manager, workspace_path)
    _log_agent_config(workspace_path)
    _register_signal_handlers(stop_event)

    log.info(
        "✅ Server Config Done — launching components",
        workspace=str(workspace_path),
        http=f"http://{config.http_host}:{config.http_port}/status",
        plugin_ws=f"ws://127.0.0.1:{config.plugin_port}",
        device_id=config.device_id,
    )

    coros = [
        run_http_server(config, stop_event),
        channel_manager.run(),
        comm_manager.run(),
        agent_manager.run(),
        metrics_collector.run(),
    ]
    if admin:
        from hirocli.ui.run import run_admin_ui
        coros.append(run_admin_ui(config, stop_event, log_dir=log_dir, workspace_path=workspace_path))

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

    if http_app.state.restart_requested:
        log.info("Restart requested — spawning new server process")
        _spawn_server(workspace_path, admin=http_app.state.restart_admin)

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

    # Clear stale PID so the new child starts clean.
    remove_pid(workspace_path, PID_FILENAME)

    stderr_log = workspace_path / "stderr.log"
    spawn_detached([*uv_python_cmd(), script], env=env, stderr_log=stderr_log)
    log.info("New server process spawning (child will write its own PID)")


if __name__ == "__main__":
    _admin = os.environ.get(ENV_ADMIN_UI) == "1"
    _metrics = os.environ.get(ENV_METRICS) == "1"
    _ws_name = os.environ.get(ENV_WORKSPACE) or None
    asyncio.run(_main(workspace_name=_ws_name, admin=_admin, metrics=_metrics))
