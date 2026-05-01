"""Channel plugin operations for the admin API."""

from __future__ import annotations

from typing import Any

from hirocli.tools.channel import ChannelDisableTool, ChannelEnableTool, ChannelListTool

from hirocli.admin.shared.result import Result


class ChannelService:
    """Facade over channel tools with explicit workspace id."""

    def list_channels(self, workspace_id: str | None) -> Result[list[dict[str, Any]]]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            result = ChannelListTool().execute(workspace=workspace_id)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(list(result.channels))

    def enable_channel(self, channel_name: str, workspace_id: str | None) -> Result[str]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        if not channel_name:
            return Result.failure("Channel name is required.")
        try:
            ChannelEnableTool().execute(channel_name=channel_name, workspace=workspace_id)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(f"Channel '{channel_name}' enabled.")

    def disable_channel(self, channel_name: str, workspace_id: str | None) -> Result[str]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        if not channel_name:
            return Result.failure("Channel name is required.")
        try:
            ChannelDisableTool().execute(channel_name=channel_name, workspace=workspace_id)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(f"Channel '{channel_name}' disabled.")
