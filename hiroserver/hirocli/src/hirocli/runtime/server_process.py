"""Entry point for the detached server process spawned by `hiro start`.

Runs the FastAPI HTTP server and the ExtensionManager concurrently inside a single
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

from hiro_commons import logging_foundation
from hiro_commons.env_file import EnvFileError, load_env_file
from hiro_commons.log import Logger
from hiro_commons.process import remove_pid, spawn_detached, uv_python_cmd, write_pid

from hirocli.constants import (
    ENV_ADMIN_UI,
    ENV_METRICS,
    ENV_SECRETS_FILE,
    ENV_SERVICE_MANAGER,
    ENV_WORKSPACE,
    ENV_WORKSPACE_PATH,
    PID_FILENAME,
    SERVICE_RESTART_EXIT_CODE,
)
from hirocli.domain.config import load_config, mark_disconnected, workspace_log_dir
from hirocli.domain.crypto import load_or_create_master_key
from hirocli.domain.character import seed_default_characters
from hirocli.domain.data_store import ensure_data_db
from hirocli.domain.db import ensure_db
from hirocli.domain.events import get_domain_event_bus
from hirocli.services import log_store
from hirocli.runtime.communication_manager import CommunicationManager
from hirocli.runtime.event_handler import EventHandler
from hirocli.runtime.extension_manager import ExtensionManager
from hirocli.runtime.http_server import app as http_app, run_http_server
from hirocli.runtime.infra_event_handlers import InfraEventHandlers
from hirocli.runtime.resource_changes_from_extensions import ResourceChangesFromExtensions
from hirocli.runtime.request_handler import RequestHandler
from hirocli.runtime.resource_change_broadcaster import ResourceChangeBroadcaster
from hirocli.runtime.resource_versioning import ResourceVersionStore
from hirocli.runtime.server_context import ServerContext
from hirocli.services.metrics import MetricsCollector
from hirocli.tools import all_tools
from hirocli.tools.registry import RuntimeContext, ToolRegistry

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


def _wire_runtime(
    ctx: ServerContext,
) -> tuple[CommunicationManager, ResourceChangeBroadcaster, ExtensionManager]:
    """Build handlers, the ExtensionManager, and CommunicationManager.

    The agent graph (formerly the adapter pipeline + post-adapt hooks) is
    owned by ``AgentManager`` now; STT/vision services are constructed
    inside ``AgentManager.serve()`` so this wiring shrinks accordingly.
    """
    event_handler = EventHandler()
    resource_versions = ResourceVersionStore()
    request_handler = RequestHandler(ctx, resource_versions=resource_versions)

    from hirocli.runtime.request_methods import register_request_methods
    register_request_methods(request_handler)

    # The one extension manager: channel plugins and apps sign in on its socket and share the request dispatcher,
    # each kind limited to the methods open to it. On ctx so admin routes can drive live channel actions
    # (enable/disable, logout, reconnect) — same loop, so they await its coroutines directly.
    extension_manager = ExtensionManager(ctx, request_handler)
    ctx.extension_manager = extension_manager

    infra_handlers = InfraEventHandlers(ctx)
    infra_handlers.register_all(extension_manager)
    log.info("Registered special channel event handlers")
    # An extension's own resource.changed goes to the core's bus (unified communication, phase 3).
    ResourceChangesFromExtensions(ctx, extension_manager).register()

    comm_manager = CommunicationManager(
        ctx=ctx,
        sink=extension_manager,
        event_handler=event_handler,
        request_handler=request_handler,
    )
    resource_change_broadcaster = ResourceChangeBroadcaster(
        ctx.workspace_path,
        comm_manager.enqueue_outbound,
        version_store=resource_versions,
        targeting=ctx.device_targeting,
    )
    resource_change_broadcaster.start()

    extension_manager.set_chat_handler(comm_manager.receive)
    # InfraEventHandlers answers the devices channel (pairing, the allowed devices) through the manager.
    infra_handlers.set_extension_manager(extension_manager)
    infra_handlers.set_resource_change_broadcaster(resource_change_broadcaster)
    # The same sender tells the apps when their copies (family, AI and voice profiles) are stale (phase 4).
    resource_change_broadcaster.set_extension_manager(extension_manager)

    return comm_manager, resource_change_broadcaster, extension_manager


def _load_service_secrets() -> None:
    """Load the service's secrets file into the environment, where the service names one (Windows and Mac).

    On Linux systemd has already loaded it. A missing or unreadable file stops the start, as a missing
    ``EnvironmentFile=`` does under systemd: a server that runs without its keys looks fine and answers nothing.
    """
    path = os.environ.get(ENV_SECRETS_FILE, "").strip()
    if not path:
        return
    try:
        names = load_env_file(Path(path))
    except EnvFileError as exc:
        log.error("❌ The service's secrets file can't be read — the server stops", path=path, reason=str(exc))
        raise SystemExit(1) from exc
    log.info("🔑 Service secrets loaded", path=path, count=len(names), names=sorted(names))


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


async def _logged_part(part) -> None:
    """Run one part of the server (a coroutine, or the admin's task); a failure is logged with its traceback, and the
    other parts go on."""
    name = getattr(part, "__qualname__", None) or (part.get_name() if isinstance(part, asyncio.Task) else repr(part))
    try:
        await part
    except asyncio.CancelledError:
        raise
    except Exception:
        log.error(f"❌ Server part stopped with an error: {name}", part=name, exc_info=True)


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
                "The server process must be started via 'hiro start'."
            )
        workspace_path = Path(ws_str)
    if workspace_name is None:
        workspace_name = os.environ.get(ENV_WORKSPACE) or workspace_path.name

    # --- Build context ---
    stop_event = asyncio.Event()
    ctx = _build_context(workspace_path, workspace_name, stop_event)

    # Bind the process-wide DomainEventBus to this loop *before* any subsystem
    # subscribes or any worker thread can publish. From here on, domain
    # mutations from admin worker threads / CLI sync code are safely
    # trampolined onto the runtime loop.
    get_domain_event_bus().attach_loop(ctx.loop)

    Logger.set_level(ctx.config.log_level)
    if ctx.config.module_log_levels:
        Logger.set_module_levels(ctx.config.module_log_levels)
    # The server's own daily file (server-<day>.jsonl) and every safety net; then this loop's errors nobody could
    # catch (a task that failed and was never awaited) land in it too.
    Logger.start(ctx.log_dir, name="server", service="core", console=foreground)
    logging_foundation.watch_loop()
    # The lines the apps (and the device app) send are kept in the same folder (logs.send; services/log_store.py)
    log_store.start(ctx.log_dir)

    log.info("🚀 Hiro Server starting...", workspace=workspace_name, foreground=foreground, admin=admin)
    # Before anything reads a provider key: they come from the environment when the keyring is off (a service).
    _load_service_secrets()
    log.info(
        f"✅ Loaded workspace '{workspace_name}' config",
        http_port=ctx.config.http_port,
        extension_port=ctx.config.effective_extension_port(),
        admin_port=ctx.config.admin_port,
        gateway_url=ctx.config.gateway_url,
        gateway_builtin=ctx.config.gateway_builtin,
        gateway_port=ctx.config.gateway_port,
        log_dir=str(ctx.log_dir),
    )

    write_pid(workspace_path, PID_FILENAME)
    ensure_db(workspace_path)
    # Characters must exist before data.db seeds the default channel (FK by id string).
    seed_default_characters(workspace_path)
    ensure_data_db(workspace_path)

    # --- Launch the admin UI as early as possible ---
    # Once `ctx` is built (line above) and both DBs exist, the admin UI has
    # everything it needs: ctx.workspace_path / ctx.config.admin_port /
    # ctx.stop_event / ctx.preferences (set in ServerContext.__post_init__) and
    # the file-backed registries the disk-reading admin pages query.
    # Routes that need late-bound state (knowledge_manager, memory_service,
    # metrics_collector, main HTTP) are already defensive and fall back to
    # on-demand construction or return a `not available` payload that the UI
    # surfaces via the readiness banner.
    # This shaves ~9 s off the "admin port bound" moment because the rest of
    # _main below (AgentManager, etc.) runs after this point.
    admin_task: asyncio.Task[None] | None = None
    if admin:
        from hirocli.admin.run import run_admin_ui_logged

        admin_task = asyncio.create_task(
            run_admin_ui_logged(ctx), name="admin_ui"
        )

    from hirocli.domain.credential_store import CredentialStore
    from hirocli.domain.workspace import workspace_id_for_path
    from hirocli.runtime.knowledge_manager import KnowledgeManager

    wid = workspace_id_for_path(workspace_path)
    cred_store = CredentialStore(workspace_path, wid) if wid is not None else None
    knowledge_manager = KnowledgeManager(ctx, credential_store=cred_store)

    # --- HTTP app state (tools registered after CommunicationManager exists — see below).
    http_app.state.ctx = ctx

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
    comm_manager, resource_change_broadcaster, extension_manager = _wire_runtime(ctx)
    # Apps' LAN names: claimed by extensions, published (mDNS) and proxied (Caddy) by the core.
    from hirocli.runtime.site_names import SiteNames

    ctx.site_names = SiteNames(ctx)
    http_app.state.channel_info_provider = extension_manager.get_channel_info
    metrics_collector.set_child_pid_provider(extension_manager.get_child_processes)

    tool_registry = ToolRegistry(
        runtime=RuntimeContext(comm_manager=comm_manager, loop=ctx.loop),
    )
    tool_registry.register_all(all_tools())
    http_app.state.tool_registry = tool_registry
    log.info(f"✅ Loaded Tool Definitions: ({len(tool_registry.names())})")

    # --- Wire agent ---
    from hirocli.runtime.agent_manager import AgentManager

    # Phase 7b step 5: no TTS service to load — voice replies use voice profiles (services/voice).
    agent_manager = AgentManager(
        ctx,
        comm_manager,
        tool_registry=tool_registry,
    )
    # Bind the runner so InboundPipeline can dispatch ``message`` payloads
    # straight into the graph runner without going through a queue.
    comm_manager.attach_agent_manager(agent_manager)
    ctx.agent_manager = agent_manager

    _register_signal_handlers(stop_event)

    log.info(
        "Server ready — launching components",
        workspace=str(workspace_path),
        http=f"http://{ctx.config.http_host}:{ctx.config.http_port}/status",
        extension_ws=f"ws://{ctx.config.extension_host}:{ctx.config.effective_extension_port()}",
        device_id=ctx.config.device_id,
    )

    # --- Launch all coroutines ---
    # Admin UI was started earlier (see the `admin_task` block above) so it can
    # bind admin_port before TTS / AgentManager / metrics startup. We include
    # the existing admin_task in the gather list so cancellation propagates on
    # shutdown.
    from hirocli.runtime.loop_sentinel import run_loop_stall_sentinel
    from hirocli.services.ai_ask.background import run_ai_background

    from hirocli.runtime.builtin_gateway import BuiltinGateway

    coros: list = [
        run_http_server(ctx),
        # Device chat's relay, beside the server while Devices is on; the devices channel connects to it.
        BuiltinGateway(ctx).run(),
        extension_manager.run(),
        ctx.site_names.run(),
        comm_manager.serve(),
        agent_manager.serve(),
        knowledge_manager.serve(),
        metrics_collector.run(),
        # Stall forensics: logs a WARNING (with duration) whenever a blocking/native call
        # starves the event loop — the silent multi-minute freezes become named evidence.
        run_loop_stall_sentinel(),
        # Phase 7a Part B: idle local models unloaded, plan sign-ins tidied, plan tools updated nightly.
        run_ai_background(ctx),
    ]
    if admin_task is not None:
        coros.append(admin_task)

    # Each part's failure is logged when it happens, with its traceback: gather's return_exceptions alone kept it
    # until the end, and the cancel at shutdown dropped it unread.
    server_task = asyncio.ensure_future(
        asyncio.gather(*(_logged_part(c) for c in coros), return_exceptions=True)
    )

    await stop_event.wait()
    await asyncio.sleep(1.5)
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        log.debug("Server parts stopped")
    finally:
        resource_change_broadcaster.close()
        if ctx.knowledge_manager is not None:
            await ctx.knowledge_manager.close()
        ctx.preference_reactor.close()
        get_domain_event_bus().detach_loop()
        log_store.stop()

    if ctx.restart_requested:
        _exit_for_service_restart(workspace_path)
        log.info("Restart requested — spawning new server process")
        _spawn_server(workspace_path, admin=ctx.restart_admin)

    mark_disconnected(workspace_path)
    log.info("hiro server exited")


def _exit_for_service_restart(workspace_path: Path) -> None:
    """Under a service manager, end with the status it restarts on; elsewhere, return (the caller spawns a successor).

    A detached successor is held by no service manager, and systemd and WinSW would kill it with this process's
    service. systemd restarts on 75 (RestartForceExitStatus=); WinSW and launchd restart on any exit but 0.
    """
    manager = os.environ.get(ENV_SERVICE_MANAGER)
    if not manager:
        return
    mark_disconnected(workspace_path)
    log.info(
        "Restart requested — exiting so the service manager starts a fresh server",
        manager=manager,
        exit_code=SERVICE_RESTART_EXIT_CODE,
    )
    raise SystemExit(SERVICE_RESTART_EXIT_CODE)


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

    # Keep the detached-process stderr log inside <workspace>/logs/ rather than the
    # workspace root, so all diagnostic files live together under the logs folder.
    log_dir = workspace_log_dir(workspace_path)
    log_dir.mkdir(parents=True, exist_ok=True)
    stderr_log = log_dir / "stderr.log"
    spawn_detached([*uv_python_cmd(), script], env=env, stderr_log=stderr_log)
    log.info("New server process spawning (child will write its own PID)")


if __name__ == "__main__":
    _admin = os.environ.get(ENV_ADMIN_UI) == "1"
    _metrics = os.environ.get(ENV_METRICS) == "1"
    _ws_name = os.environ.get(ENV_WORKSPACE) or None
    asyncio.run(_main(workspace_name=_ws_name, admin=_admin, metrics=_metrics))
