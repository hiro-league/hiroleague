"""Server lifecycle tools: setup, start, stop, status, teardown.

These tools own the CLI/agent-facing schema and delegate all heavy lifting
to ``server_control`` (process management, bootstrap) and return dataclasses
from ``server_models``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from hiro_commons.keys import public_key_to_b64
from hiro_commons.process import is_running, read_pid

from ..domain.config import Config, load_config, load_state, master_key_path, save_config
from ..domain.crypto import load_or_create_master_key
from ..domain.workspace import (
    admin_port_for,
    http_port_for,
    load_registry,
    plugin_port_for,
    remove_workspace,
    resolve_workspace,
    WorkspaceError,
)
from ..constants import PID_FILENAME
from .base import Tool, ToolParam
from . import server_control as ctrl
from .server_models import (
    RestartResult,
    SetupResult,
    StartResult,
    StatusResult,
    StopResult,
    TeardownResult,
    UninstallResult,
    WorkspaceStatusEntry,
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class SetupTool(Tool):
    name = "setup"
    description = (
        "One-time setup: save gateway config, generate device key, "
        "and optionally register auto-start and start the server"
    )
    params = {
        "gateway_url": ToolParam(str, "WebSocket gateway URL, e.g. ws://myhost:8765"),
        "workspace": ToolParam(str, "Workspace name or id to configure", required=False),
        "http_port": ToolParam(int, "Local HTTP server port override", required=False),
        "skip_autostart": ToolParam(bool, "Do not register auto-start", required=False),
        "start_server": ToolParam(
            bool,
            "Start the server after setup completes (default: false)",
            required=False,
        ),
        "elevated_task": ToolParam(
            bool,
            "(Windows) Request UAC elevation for Task Scheduler entry",
            required=False,
        ),
        "metrics_enabled": ToolParam(bool, "Enable system metrics collection", required=False),
        "metrics_interval": ToolParam(float, "Metrics sampling interval in seconds", required=False),
    }

    def execute(
        self,
        gateway_url: str,
        workspace: str | None = None,
        http_port: int | None = None,
        skip_autostart: bool = False,
        start_server: bool = False,
        elevated_task: bool = False,
        metrics_enabled: bool | None = None,
        metrics_interval: float | None = None,
    ) -> SetupResult:
        entry, registry, workspace_path = ctrl.resolve_or_create(workspace)
        existing = load_config(workspace_path)

        config = Config(
            device_id=existing.device_id,
            gateway_url=gateway_url,
            http_host=existing.http_host,
            http_port=http_port or http_port_for(registry, entry.port_slot),
            plugin_port=plugin_port_for(registry, entry.port_slot),
            admin_port=admin_port_for(registry, entry.port_slot),
            master_key_file=existing.master_key_file,
            pairing_code_length=existing.pairing_code_length,
            pairing_code_ttl_seconds=existing.pairing_code_ttl_seconds,
            attestation_expires_days=existing.attestation_expires_days,
            metrics_enabled=metrics_enabled if metrics_enabled is not None else existing.metrics_enabled,
            metrics_interval=metrics_interval if metrics_interval is not None else existing.metrics_interval,
            metrics_history_size=existing.metrics_history_size,
        )
        save_config(workspace_path, config)
        private_key = load_or_create_master_key(workspace_path, filename=config.master_key_file)
        public_key_b64 = public_key_to_b64(private_key.public_key())
        ctrl.ensure_mandatory_devices_channel(workspace_path, config)
        ctrl.ensure_default_preferences(workspace_path)

        from ..domain.credential_store import CredentialStore

        providers_imported = CredentialStore(workspace_path, entry.id).import_detected_env_keys()
        if providers_imported:
            from hiro_commons.log import Logger

            Logger.get("TOOLS.SETUP").info(
                "✅ Imported provider API keys from environment — HiroServer · setup",
                count=providers_imported,
                workspace=entry.name,
            )

        autostart_registered = False
        autostart_method = "skipped"
        if not skip_autostart:
            autostart_registered, autostart_method = ctrl.register_autostart_for_workspace(
                entry.id, elevated_task,
            )

        config.autostart_method = autostart_method
        save_config(workspace_path, config)

        if start_server:
            ctrl.start_server(workspace_path, config, workspace_name=entry.name, foreground=False)

        return SetupResult(
            workspace=entry.name,
            workspace_path=str(workspace_path),
            device_id=config.device_id,
            gateway_url=config.gateway_url,
            http_port=config.http_port,
            master_key=str(master_key_path(workspace_path, config)),
            desktop_pub=public_key_b64,
            autostart_registered=autostart_registered,
            autostart_method=autostart_method,
            server_started=start_server,
            providers_imported=providers_imported,
        )


class StartTool(Tool):
    name = "start"
    description = "Start the hirocli server for a workspace (background by default)"
    params = {
        "workspace": ToolParam(str, "Workspace name or id to start", required=False),
        "foreground": ToolParam(
            bool,
            "Run the server in the foreground with live log output",
            required=False,
        ),
        "admin": ToolParam(
            bool,
            "Also start the admin UI on its dedicated port",
            required=False,
        ),
        "metrics": ToolParam(
            bool,
            "Enable system metrics collection for this run",
            required=False,
        ),
    }

    def execute(
        self,
        workspace: str | None = None,
        foreground: bool = False,
        admin: bool = False,
        metrics: bool = False,
    ) -> StartResult:
        entry, registry, workspace_path = ctrl.resolve_or_create(workspace)

        if not (workspace_path / "config.json").exists():
            raise ValueError(
                f"Workspace '{entry.name}' is not configured. "
                f"Run 'hirocli setup --workspace {entry.name}' first."
            )

        config = load_config(workspace_path)

        pid = read_pid(workspace_path, PID_FILENAME)
        if pid and is_running(pid):
            return StartResult(
                workspace=entry.name,
                workspace_path=str(workspace_path),
                already_running=True,
                pid=pid,
                http_host=config.http_host,
                http_port=config.http_port,
                admin_port=config.admin_port if admin else None,
            )

        ctrl.start_server(
            workspace_path, config,
            workspace_name=entry.name, foreground=foreground, admin=admin, metrics=metrics,
        )

        new_pid = read_pid(workspace_path, PID_FILENAME)
        return StartResult(
            workspace=entry.name,
            workspace_path=str(workspace_path),
            already_running=False,
            pid=new_pid,
            http_host=config.http_host,
            http_port=config.http_port,
            admin_port=config.admin_port if admin else None,
        )


class StopTool(Tool):
    name = "stop"
    description = "Stop the running hirocli server for a workspace"
    params = {
        "workspace": ToolParam(str, "Workspace name or id to stop", required=False),
    }

    def execute(self, workspace: str | None = None) -> StopResult:
        entry, _, workspace_path = ctrl.resolve_or_create(workspace)
        pid = read_pid(workspace_path, PID_FILENAME)
        was_running = pid is not None and is_running(pid)
        ctrl.stop_server(workspace_path)
        return StopResult(workspace=entry.name, was_running=was_running, pid=pid)


class RestartTool(Tool):
    name = "restart"
    description = "Gracefully restart the hirocli server for a workspace"
    params = {
        "workspace": ToolParam(str, "Workspace name or id to restart", required=False),
        "foreground": ToolParam(
            bool,
            "Run the restarted server in the foreground with live log output",
            required=False,
        ),
        "admin": ToolParam(
            bool,
            "Also start the admin UI on its dedicated port",
            required=False,
        ),
        "metrics": ToolParam(
            bool,
            "Enable system metrics collection for this run",
            required=False,
        ),
    }

    def execute(
        self,
        workspace: str | None = None,
        foreground: bool = False,
        admin: bool = False,
        metrics: bool = False,
    ) -> RestartResult:
        entry, _, workspace_path = ctrl.resolve_or_create(workspace)

        if not (workspace_path / "config.json").exists():
            raise ValueError(
                f"Workspace '{entry.name}' is not configured. "
                f"Run 'hirocli setup --workspace {entry.name}' first."
            )

        config = load_config(workspace_path)
        pid = read_pid(workspace_path, PID_FILENAME)
        was_running = pid is not None and is_running(pid)

        if was_running:
            if os.getpid() == pid:
                from hirocli.runtime.http_server import request_restart

                request_restart(admin=admin)
                return RestartResult(
                    workspace=entry.name,
                    workspace_path=str(workspace_path),
                    was_running=True,
                    pid=pid,
                    new_pid=None,
                    http_host=config.http_host,
                    http_port=config.http_port,
                    admin_port=config.admin_port if admin else None,
                )

            ctrl.stop_server(workspace_path)

        ctrl.start_server(
            workspace_path, config,
            workspace_name=entry.name, foreground=foreground, admin=admin, metrics=metrics,
        )

        new_pid = read_pid(workspace_path, PID_FILENAME)
        return RestartResult(
            workspace=entry.name,
            workspace_path=str(workspace_path),
            was_running=was_running,
            pid=pid,
            new_pid=new_pid,
            http_host=config.http_host,
            http_port=config.http_port,
            admin_port=config.admin_port if admin else None,
        )


class StatusTool(Tool):
    name = "status"
    description = "Show server and WebSocket connection status for one or all workspaces"
    params = {
        "workspace": ToolParam(
            str,
            "Workspace name or id to query (omit to show all workspaces)",
            required=False,
        ),
    }

    def execute(self, workspace: str | None = None) -> StatusResult:
        registry = load_registry()

        if not registry.workspaces:
            return StatusResult(workspaces=[])

        if workspace is not None:
            entry, _ = resolve_workspace(workspace)
            ids = [entry.id]
        else:
            ids = list(registry.workspaces.keys())

        entries = []
        for ws_id in ids:
            ws_entry = registry.workspaces[ws_id]
            ws_path = Path(ws_entry.path)
            pid = read_pid(ws_path, "hirocli.pid")
            running = is_running(pid)
            state = load_state(ws_path)
            config = load_config(ws_path)
            entries.append(
                WorkspaceStatusEntry(
                    id=ws_id,
                    name=ws_entry.name,
                    is_default=ws_id == registry.default_workspace,
                    server_running=running,
                    pid=pid,
                    ws_connected=state.ws_connected,
                    last_connected=state.last_connected,
                    gateway_url=state.gateway_url or config.gateway_url or None,
                    device_id=config.device_id,
                    http_host=config.http_host,
                    http_port=config.http_port,
                )
            )
        return StatusResult(workspaces=entries)


class TeardownTool(Tool):
    name = "teardown"
    description = "Stop server and remove all auto-start registrations for a workspace"
    params = {
        "workspace": ToolParam(str, "Workspace name or id to tear down", required=False),
        "purge": ToolParam(
            bool,
            "Also delete the workspace folder (config, state, keys, logs…)",
            required=False,
        ),
    }

    def execute(
        self,
        workspace: str | None = None,
        purge: bool = False,
    ) -> TeardownResult:
        entry, registry, workspace_path = ctrl.resolve_or_create(workspace)

        ctrl.stop_server(workspace_path)

        stored_config = load_config(workspace_path)
        autostart_removed = ctrl.unregister_autostart_for_workspace(entry.id, stored_config.autostart_method)

        if purge:
            if workspace_path.exists():
                shutil.rmtree(workspace_path, ignore_errors=True)
            try:
                remove_workspace(entry.id, purge=False)
            except WorkspaceError:
                pass

        return TeardownResult(
            workspace=entry.name,
            workspace_path=str(workspace_path),
            server_stopped=True,
            autostart_removed=autostart_removed,
            purged=purge,
        )


class UninstallTool(Tool):
    name = "uninstall"
    description = "Stop server, remove auto-start, and return package uninstall instructions"
    params = {
        "workspace": ToolParam(str, "Workspace name or id to uninstall", required=False),
        "purge": ToolParam(bool, "Also delete the workspace folder", required=False),
    }

    def execute(
        self,
        workspace: str | None = None,
        purge: bool = False,
    ) -> UninstallResult:
        teardown_result = TeardownTool().execute(workspace=workspace, purge=purge)
        return UninstallResult(teardown=teardown_result)
