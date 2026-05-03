"""Conversation channel and message history tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.conversation_channel import (
    create_channel,
    delete_channel,
    update_channel,
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
    if channel_name is not None and user_id is None:
        raise ValueError("user_id is required when resolving a channel by name")

    channel = None
    if channel_id is not None:
        channel = _get_channel_by_id(workspace_path, channel_id)
    elif channel_name is not None:
        channel = _get_channel_by_name(workspace_path, channel_name, user_id=user_id)

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
class ConversationChannelCreateResult:
    channel: dict[str, Any]


@dataclass
class ConversationChannelUpdateResult:
    channel: dict[str, Any]


@dataclass
class ConversationChannelDeleteResult:
    deleted_channel_id: int


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
    description = "Get a conversation channel by id or by user-scoped name; falls back to that user's General channel if not found"
    params = {
        "channel_id": ToolParam(int, "Channel integer id", required=False),
        "channel_name": ToolParam(str, "Channel name", required=False),
        "user_id": ToolParam(int, "Owning user id; required when channel_name is provided", required=False),
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


class ConversationChannelCreateTool(Tool):
    name = "conversation_channel_create"
    description = "Create a conversation channel for a specific user and character"
    params = {
        "channel_name": ToolParam(str, "Channel name"),
        "user_id": ToolParam(int, "Owning user id"),
        "character_id": ToolParam(str, "Character id (slug) for this conversation"),
        "channel_type": ToolParam(str, "Channel type (default: direct)", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(
        self,
        channel_name: str,
        user_id: int,
        character_id: str,
        channel_type: str = "direct",
        workspace: str | None = None,
        *,
        workspace_path: Path | None = None,
    ) -> ConversationChannelCreateResult:
        resolved_workspace_path = workspace_path or _resolve_path(workspace)
        channel = create_channel(
            resolved_workspace_path,
            name=channel_name,
            character_id=character_id,
            user_id=user_id,
            channel_type=channel_type,
        )
        return ConversationChannelCreateResult(channel=channel.model_dump())


class ConversationChannelUpdateTool(Tool):
    name = "conversation_channel_update"
    description = "Update an existing conversation channel; only provided fields are changed"
    params = {
        "channel_id": ToolParam(int, "Channel integer id"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
        "channel_name": ToolParam(str, "Channel display name", required=False),
        "channel_type": ToolParam(str, "Channel type (e.g. direct)", required=False),
        "character_id": ToolParam(str, "Character id (slug)", required=False),
        "user_id": ToolParam(int, "Owning user id", required=False),
    }

    def execute(
        self,
        channel_id: int,
        workspace: str | None = None,
        *,
        workspace_path: Path | None = None,
        channel_name: str | None = None,
        channel_type: str | None = None,
        character_id: str | None = None,
        user_id: int | None = None,
    ) -> ConversationChannelUpdateResult:
        if (
            channel_name is None
            and channel_type is None
            and character_id is None
            and user_id is None
        ):
            raise ValueError(
                "At least one of channel_name, channel_type, character_id, or user_id must be provided."
            )
        resolved = workspace_path or _resolve_path(workspace)
        channel = update_channel(
            resolved,
            channel_id,
            name=channel_name,
            channel_type=channel_type,
            character_id=character_id,
            user_id=user_id,
        )
        return ConversationChannelUpdateResult(channel=channel.model_dump())


class ConversationChannelDeleteTool(Tool):
    name = "conversation_channel_delete"
    description = "Delete a conversation channel and all messages in it"
    params = {
        "channel_id": ToolParam(int, "Channel integer id"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(
        self,
        channel_id: int,
        workspace: str | None = None,
        *,
        workspace_path: Path | None = None,
    ) -> ConversationChannelDeleteResult:
        resolved = workspace_path or _resolve_path(workspace)
        delete_channel(resolved, channel_id)
        return ConversationChannelDeleteResult(deleted_channel_id=channel_id)


class MessageHistoryTool(Tool):
    name = "message_history"
    description = (
        "Retrieve message history for a conversation channel. "
        "Use all_messages=true for no row limit; otherwise limit defaults to 50."
    )
    params = {
        "channel_id": ToolParam(int, "Channel integer id"),
        "after": ToolParam(str, "ISO 8601 timestamp - return only messages after this time", required=False),
        "limit": ToolParam(int, "Max messages when all_messages is false (default 50)", required=False),
        "all_messages": ToolParam(
            bool,
            "If true, return every message in the channel (ignores limit)",
            required=False,
        ),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(
        self,
        channel_id: int,
        after: str | None = None,
        limit: int = 50,
        all_messages: bool = False,
        workspace: str | None = None,
    ) -> MessageHistoryResult:
        from ..domain.message_store import _sync_list

        workspace_path = _resolve_path(workspace)
        eff_limit: int | None = None if all_messages else limit
        messages = _sync_list(workspace_path, channel_id, after=after, limit=eff_limit)
        return MessageHistoryResult(messages=messages, channel_id=channel_id)
