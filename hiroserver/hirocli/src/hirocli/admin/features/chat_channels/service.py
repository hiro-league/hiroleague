"""Conversation channels + message history — wraps conversation tools; no NiceGUI (§1.3)."""

from __future__ import annotations

from typing import Any

from hirocli.tools.conversation import (
    ConversationChannelCreateTool,
    ConversationChannelDeleteTool,
    ConversationChannelListTool,
    ConversationChannelUpdateTool,
    MessageHistoryTool,
)

from hirocli.admin.shared.result import Result


class ChatChannelsService:
    """Facade over conversation tools with explicit workspace id."""

    def list_channels(self, workspace_id: str | None) -> Result[list[dict[str, Any]]]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            out = ConversationChannelListTool().execute(workspace=workspace_id)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(list(out.channels))

    def create_channel(
        self,
        workspace_id: str | None,
        *,
        name: str,
        user_id: int,
        agent_id: str,
        channel_type: str = "direct",
    ) -> Result[dict[str, Any]]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        if not name.strip():
            return Result.failure("Name is required.")
        try:
            out = ConversationChannelCreateTool().execute(
                channel_name=name.strip(),
                user_id=user_id,
                agent_id=agent_id.strip(),
                channel_type=channel_type.strip() or "direct",
                workspace=workspace_id,
            )
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(out.channel)

    def update_channel(
        self,
        workspace_id: str | None,
        channel_id: int,
        *,
        name: str | None = None,
        channel_type: str | None = None,
        agent_id: str | None = None,
        user_id: int | None = None,
    ) -> Result[dict[str, Any]]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            out = ConversationChannelUpdateTool().execute(
                channel_id,
                workspace=workspace_id,
                channel_name=name,
                channel_type=channel_type,
                agent_id=agent_id,
                user_id=user_id,
            )
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(out.channel)

    def delete_channel(self, workspace_id: str | None, channel_id: int) -> Result[int]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            ConversationChannelDeleteTool().execute(channel_id, workspace=workspace_id)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(channel_id)

    def list_messages_all(
        self,
        workspace_id: str | None,
        channel_id: int,
    ) -> Result[list[dict[str, Any]]]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            out = MessageHistoryTool().execute(
                channel_id,
                workspace=workspace_id,
                all_messages=True,
            )
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(list(out.messages))
