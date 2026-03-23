"""Result dataclasses returned by server lifecycle tools."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SetupResult:
    workspace: str
    workspace_path: str
    device_id: str
    gateway_url: str
    http_port: int
    master_key: str
    desktop_pub: str
    autostart_registered: bool
    autostart_method: str  # "schtasks" | "registry" | "elevated" | "skipped" | "failed"
    server_started: bool


@dataclass
class StartResult:
    workspace: str
    workspace_path: str
    already_running: bool
    pid: int | None
    http_host: str
    http_port: int
    admin_port: int | None = None


@dataclass
class StopResult:
    workspace: str
    was_running: bool
    pid: int | None


@dataclass
class RestartResult:
    workspace: str
    workspace_path: str
    was_running: bool
    pid: int | None
    new_pid: int | None
    http_host: str
    http_port: int
    admin_port: int | None = None


@dataclass
class WorkspaceStatusEntry:
    id: str
    name: str
    is_default: bool
    server_running: bool
    pid: int | None
    ws_connected: bool
    last_connected: str | None
    gateway_url: str | None
    device_id: str
    http_host: str
    http_port: int


@dataclass
class StatusResult:
    workspaces: list[WorkspaceStatusEntry] = field(default_factory=list)


@dataclass
class TeardownResult:
    workspace: str
    workspace_path: str
    server_stopped: bool
    autostart_removed: bool
    purged: bool


@dataclass
class UninstallResult:
    teardown: TeardownResult
