"""Dashboard aggregate stats — wraps workspace/server/gateway/device/channel tools (no NiceGUI)."""

from __future__ import annotations

from dataclasses import dataclass

from hiro_commons.log import Logger

from hirocli.admin.shared.result import Result
from hirocli.tools.channel import ChannelListTool
from hirocli.tools.device import DeviceListTool
from hirocli.tools.gateway import GatewayStatusTool
from hirocli.tools.server import StatusTool
from hirocli.tools.workspace import WorkspaceListTool

log = Logger.get("ADMIN.DASHBOARD")


@dataclass(frozen=True)
class DashboardData:
    """Snapshot for the dashboard stat grid (same semantics as legacy dashboard page)."""

    total_workspaces: int
    running_workspaces: int
    gateway_running: bool
    gateway_desktop_connected: bool
    gateway_auth_error: str | None
    total_devices: int
    total_channels: int
    enabled_channels: int


class DashboardService:
    """Loads cross-workspace aggregates; returns Result.failure if workspace list cannot load."""

    def get_overview(self) -> Result[DashboardData]:
        try:
            ws_result = WorkspaceListTool().execute()
            workspaces = ws_result.workspaces
        except Exception as exc:
            return Result.failure(f"Unable to load workspaces: {exc}")

        total_workspaces = len(workspaces)

        running_workspaces = 0
        try:
            status_result = StatusTool().execute()
            running_workspaces = sum(1 for w in status_result.workspaces if w.server_running)
        except Exception as exc:
            # Guidelines §10 / general-coding-rules: no silent swallow — log partial-failure paths.
            log.warning(
                "⚠️ Partial dashboard aggregate — HiroServer · StatusTool failed",
                error=str(exc),
                exc_info=True,
            )

        gateway_running = False
        gateway_desktop_connected = False
        gateway_auth_error: str | None = None
        try:
            gw_result = GatewayStatusTool().execute()
            gateway_running = any(inst.running for inst in gw_result.instances)
            gateway_desktop_connected = any(inst.desktop_connected for inst in gw_result.instances)
            for inst in gw_result.instances:
                if inst.last_auth_error:
                    gateway_auth_error = inst.last_auth_error
                    break
        except Exception as exc:
            log.warning(
                "⚠️ Partial dashboard aggregate — HiroServer · GatewayStatusTool failed",
                error=str(exc),
                exc_info=True,
            )

        total_devices = 0
        total_channels = 0
        enabled_channels = 0
        for ws in workspaces:
            ws_id: str | None = ws.get("id")
            try:
                devices = DeviceListTool().execute(workspace=ws_id)
                total_devices += len(devices.devices)
            except Exception as exc:
                log.warning(
                    "⚠️ Partial dashboard aggregate — HiroServer · DeviceListTool failed",
                    error=str(exc),
                    workspace_id=ws_id,
                    exc_info=True,
                )
            try:
                channels = ChannelListTool().execute(workspace=ws_id)
                total_channels += len(channels.channels)
                enabled_channels += sum(1 for c in channels.channels if c.get("enabled"))
            except Exception as exc:
                log.warning(
                    "⚠️ Partial dashboard aggregate — HiroServer · ChannelListTool failed",
                    error=str(exc),
                    workspace_id=ws_id,
                    exc_info=True,
                )

        return Result.success(
            DashboardData(
                total_workspaces=total_workspaces,
                running_workspaces=running_workspaces,
                gateway_running=gateway_running,
                gateway_desktop_connected=gateway_desktop_connected,
                gateway_auth_error=gateway_auth_error,
                total_devices=total_devices,
                total_channels=total_channels,
                enabled_channels=enabled_channels,
            )
        )
