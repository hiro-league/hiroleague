"""Conversation channel and message history tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.conversation_channel import (
    _get_channel_by_id,
    _get_channel_by_name,
    _get_default_channel,
    _list_channels,
)
from ..domain.workspace import resolve_workspace
from .base import Tool, ToolParam


def _resolve_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


def _resolve_channel(
    workspace_path: Path,
    *,
    channel_id: int | None = None,
    channel_name: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any] | None:
    if channel_id is None and channel_name is None:
        raise ValueError("channel_id or channel_name is required")

    channel = None
    if channel_id is not None:
        channel = _get_channel_by_id(workspace_path, channel_id)
    elif channel_name is not None:
        channel = _get_channel_by_name(workspace_path, channel_name)

    if channel is None:
        channel = _get_default_channel(workspace_path, user_id=user_id)

    return channel.model_dump() if channel else None


@dataclass
class ConversationChannelListResult:
    channels: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ConversationChannelGetResult:
    channel: dict[str, Any] | None = None


@dataclass
class MessageHistoryResult:
    messages: list[dict[str, Any]] = field(default_factory=list)
    channel_id: int = 0


class ConversationChannelListTool(Tool):
    name = "conversation_channel_list"
    description = "List all conversation channels (active conversations) and their metadata"
    params = {
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, workspace: str | None = None) -> ConversationChannelListResult:
        workspace_path = _resolve_path(workspace)
        channels = _list_channels(workspace_path)
        return ConversationChannelListResult(
            channels=[ch.model_dump() for ch in channels],
        )


class ConversationChannelGetTool(Tool):
    name = "conversation_channel_get"
    description = "Get a conversation channel by id or name; falls back to General if not found"
    params = {
        "channel_id": ToolParam(int, "Channel integer id", required=False),
        "channel_name": ToolParam(str, "Channel name", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(
        self,
        channel_id: int | None = None,
        channel_name: str | None = None,
        workspace: str | None = None,
        *,
        workspace_path: Path | None = None,
        user_id: int | None = None,
    ) -> ConversationChannelGetResult:
        resolved_workspace_path = workspace_path or _resolve_path(workspace)
        channel = _resolve_channel(
            resolved_workspace_path,
            channel_id=channel_id,
            channel_name=channel_name,
            user_id=user_id,
        )
        return ConversationChannelGetResult(channel=channel)


class MessageHistoryTool(Tool):
    name = "message_history"
    description = "Retrieve message history for a conversation channel, with optional pagination"
    params = {
        "channel_id": ToolParam(int, "Channel integer id"),
        "after": ToolParam(str, "ISO 8601 timestamp - return only messages after this time", required=False),
        "limit": ToolParam(int, "Max messages to return (default 50)", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(
        self,
        channel_id: int,
        after: str | None = None,
        limit: int = 50,
        workspace: str | None = None,
    ) -> MessageHistoryResult:
        from ..domain.message_store import _sync_list

        workspace_path = _resolve_path(workspace)
        messages = _sync_list(workspace_path, channel_id, after=after, limit=limit)
        return MessageHistoryResult(messages=messages, channel_id=channel_id)
