"""Server lifecycle tools: setup, start, stop, status, teardown.

These tools own the CLI/agent-facing schema and delegate all heavy lifting
to ``server_control`` (process management, bootstrap) and return dataclasses
from ``server_models``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from hiro_commons.keys import public_key_to_b64
from hiro_commons.log import Logger
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
    UpgradeResult,
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
        "skip_env_import": ToolParam(
            bool,
            "Skip auto-import of API keys from environment (CLI will provision interactively)",
            required=False,
        ),
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
        skip_env_import: bool = False,
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
        from ..domain.onboarding_defaults import apply_onboarding_defaults_to_preferences

        providers_imported = 0
        if not skip_env_import:
            cred_store = CredentialStore(workspace_path, entry.id)
            providers_imported = cred_store.import_detected_env_keys()
            if providers_imported:
                from hiro_commons.log import Logger

                Logger.get("TOOLS.SETUP").info(
                    "✅ Imported provider API keys from environment — HiroServer · setup",
                    count=providers_imported,
                    workspace=entry.name,
                )
            # Phase 3c: fill empty default_* slots from catalog (non-interactive — no prompt).
            ordered = [m.provider_id for m in cred_store.list_configured()]
            applied = apply_onboarding_defaults_to_preferences(
                workspace_path, entry.id, ordered,
            )
            if applied:
                from hiro_commons.log import Logger

                Logger.get("TOOLS.SETUP").info(
                    "✅ Applied catalog default models — HiroServer · setup · onboarding",
                    models=", ".join(f"{s.catalog_kind}={s.model_id}" for s in applied),
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
            workspace_id=entry.id,
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
    description = "Start the Hiro server for a workspace (background by default)"
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
                f"Run 'hiro workspaces setup {entry.name}' first."
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
    description = "Stop the running Hiro server for a workspace"
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
    description = "Gracefully restart the Hiro server for a workspace"
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
                f"Run 'hiro workspaces setup {entry.name}' first."
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
            pid = read_pid(ws_path, PID_FILENAME)
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


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------
#
# `hiro upgrade` exists because `uv tool upgrade hiroleague` alone does not
# always pick up newer versions: uv records the *resolved* version of an
# unconstrained tool spec in its receipt, so subsequent `upgrade` calls can
# report "Nothing to upgrade" even when PyPI has a newer release. The
# documented escape hatch is `uv tool upgrade --reinstall`, which deletes the
# tool venv and re-resolves from scratch. That's safe — Python wheels have no
# install/uninstall hooks, and user-data directories live outside the venv.
#
# We hide that behind a simple `hiro upgrade` so end users never need to know
# about uv's quirks. The same command also handles workspace devs (editable
# installs) and pip/pipx users by detecting the install method.


def _detect_install_method(installed_path: Path | None) -> tuple[str, str]:
    """Classify how the currently-running `hirocli` is installed.

    Returns ``(method, explanation)``. See ``UpgradeResult.install_method``
    for the list of methods.

    Detection is best-effort and based on the install path. We can't ask
    uv "did you install this?" directly, so we recognise its standard
    layout (``…/uv/tools/<name>/…``) and pipx's (``…/pipx/venvs/<name>/…``).
    """
    if installed_path is None:
        return "unknown", "Could not determine where hirocli is installed."

    path_str = str(installed_path).replace("\\", "/").lower()

    # uv tool layout: <data-dir>/uv/tools/<tool-name>/lib/...
    if "/uv/tools/" in path_str:
        if "/uv/tools/hiroleague/" in path_str:
            return (
                "uv-tool-hiroleague",
                "Installed via `uv tool install hiroleague` (end-user meta-package).",
            )
        if "/uv/tools/hirocli/" in path_str:
            return (
                "uv-tool-hirocli",
                "Installed via `uv tool install --editable hirocli` (workspace dev).",
            )
        return (
            "uv-tool-hirocli",
            "Installed via `uv tool install` (uv tool layout detected).",
        )

    # pipx layout: <data-dir>/pipx/venvs/<tool-name>/lib/...
    if "/pipx/venvs/" in path_str:
        return (
            "pipx-hiroleague",
            "Installed via `pipx install hiroleague`.",
        )

    # Editable installs leave a .pth file or an `__editable__` finder; the
    # easiest signal is whether the package metadata points at a source tree
    # we can write into. Best-effort: if the path contains "src/hirocli", it's
    # an editable workspace install (e.g. `uv pip install -e .`).
    if "/src/hirocli" in path_str:
        return (
            "editable",
            "Editable install detected — upgrade by pulling the repo and re-running `uv sync`.",
        )

    return "pip", "Installed via pip into a regular Python environment."


def _build_upgrade_command(method: str) -> list[str] | None:
    """Return the recommended shell command for the given install method.

    ``None`` means there's no fully-automatic upgrade path (editable /
    unknown) — the user has to handle it themselves.
    """
    if method == "uv-tool-hiroleague":
        # --reinstall forces uv to drop the cached pin and re-resolve, which
        # is the only way to escape "Nothing to upgrade" on already-pinned
        # tool installs.
        return ["uv", "tool", "upgrade", "--reinstall", "hiroleague"]
    if method == "uv-tool-hirocli":
        return ["uv", "tool", "upgrade", "--reinstall", "hirocli"]
    if method == "pipx-hiroleague":
        return ["pipx", "upgrade", "hiroleague"]
    if method == "pip":
        # `python -m pip` (rather than bare `pip`) so we hit the same
        # interpreter that's running `hiro` — avoids the classic "wrong pip"
        # footgun on systems with multiple Pythons.
        return [sys.executable, "-m", "pip", "install", "--upgrade", "hiroleague"]
    return None


class UpgradeTool(Tool):
    name = "upgrade"
    description = (
        "Detect how Hiro is installed and run the right upgrade command "
        "(uv tool upgrade --reinstall / pipx / pip)"
    )
    params = {
        "workspace": ToolParam(
            str,
            "Workspace whose server should be stopped before upgrading "
            "(default: registry default)",
            required=False,
        ),
        "dry_run": ToolParam(
            bool,
            "Detect install method and print the recommended command, "
            "but do not run it",
            required=False,
        ),
        "stop_server": ToolParam(
            bool,
            "Stop the running server before upgrading (default: true). "
            "Required on Windows to release locked files in the venv.",
            required=False,
        ),
        "restart_server": ToolParam(
            bool,
            "Start the server again after a successful upgrade if it was "
            "running before (default: true)",
            required=False,
        ),
    }

    def execute(
        self,
        workspace: str | None = None,
        dry_run: bool = False,
        stop_server: bool = True,
        restart_server: bool = True,
    ) -> UpgradeResult:
        log = Logger.get("TOOLS.UPGRADE")

        # Resolve the package version + install path. We prefer the umbrella
        # `hiroleague` metadata when present (end-user install); fall back to
        # `hirocli` for workspace devs.
        version_str = "unknown"
        install_path: Path | None = None
        for name in ("hiroleague", "hirocli"):
            try:
                version_str = metadata.version(name)
                dist = metadata.distribution(name)
                if dist.locate_file(""):
                    install_path = Path(str(dist.locate_file("")))
                break
            except metadata.PackageNotFoundError:
                continue

        method, explanation = _detect_install_method(install_path)
        upgrade_cmd = _build_upgrade_command(method)

        # Inspect the server state for the requested (or default) workspace
        # so we can stop/restart around the upgrade. We tolerate "no
        # workspace yet" — a user might be upgrading before they've ever
        # configured one.
        server_was_running = False
        server_pid: int | None = None
        server_workspace: str | None = None
        workspace_path: Path | None = None
        config_for_restart: Config | None = None
        try:
            entry, _, workspace_path = ctrl.resolve_or_create(workspace)
            server_workspace = entry.name
            server_pid = read_pid(workspace_path, PID_FILENAME)
            server_was_running = server_pid is not None and is_running(server_pid)
            if server_was_running and (workspace_path / "config.json").exists():
                config_for_restart = load_config(workspace_path)
        except WorkspaceError:
            pass

        if dry_run or upgrade_cmd is None:
            log.info(
                "Upgrade plan — HiroServer · upgrade",
                method=method,
                version=version_str,
                command=" ".join(upgrade_cmd) if upgrade_cmd else "(none)",
            )
            return UpgradeResult(
                installed_version=version_str,
                install_method=method,
                upgrade_command=upgrade_cmd,
                explanation=explanation,
                server_was_running=server_was_running,
                server_pid=server_pid,
                server_workspace=server_workspace,
                executed=False,
                exit_code=None,
                server_restarted=False,
            )

        if stop_server and server_was_running and workspace_path is not None:
            log.info(
                "Stopping server before upgrade — HiroServer · upgrade",
                workspace=server_workspace,
                pid=server_pid,
            )
            ctrl.stop_server(workspace_path)

        log.info(
            "⬆️ Running upgrade — HiroServer · upgrade",
            method=method,
            command=" ".join(upgrade_cmd),
        )
        # We deliberately don't capture stdout/stderr — uv/pipx/pip print
        # nicely-formatted progress that the user benefits from seeing live.
        # Failure surfaces via the returncode; we log it and let the CLI
        # layer render it.
        try:
            proc = subprocess.run(upgrade_cmd, check=False)
            exit_code = proc.returncode
        except FileNotFoundError as exc:
            log.error(
                "❌ Upgrade command not found — HiroServer · upgrade",
                command=upgrade_cmd[0],
                error=str(exc),
                exc_info=True,
            )
            exit_code = 127

        upgrade_ok = exit_code == 0
        server_restarted = False
        if (
            upgrade_ok
            and restart_server
            and server_was_running
            and workspace_path is not None
            and config_for_restart is not None
        ):
            log.info(
                "Restarting server after upgrade — HiroServer · upgrade",
                workspace=server_workspace,
            )
            ctrl.start_server(
                workspace_path,
                config_for_restart,
                workspace_name=server_workspace or "default",
                foreground=False,
            )
            server_restarted = True

        return UpgradeResult(
            installed_version=version_str,
            install_method=method,
            upgrade_command=upgrade_cmd,
            explanation=explanation,
            server_was_running=server_was_running,
            server_pid=server_pid,
            server_workspace=server_workspace,
            executed=True,
            exit_code=exit_code,
            server_restarted=server_restarted,
        )
