"""Conversation channel and message history tools."""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_channel_sdk.constants import MESSAGE_TYPE_MESSAGE
from hiro_channel_sdk.models import ContentItem, MessageRouting, UnifiedMessage
from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME

from ..domain.blob_store import DEFAULT_CHUNK_SIZE, blob_id_for_bytes, chunk_count_for_size
from ..domain.conversation_channel import (
    clear_channel_messages,
    create_channel,
    delete_channel,
    update_channel,
    _get_channel_by_id,
    _get_channel_by_name,
    _get_default_channel,
)
from ..domain.server_info import build_channel_list_entries
from ..domain.data_store import get_default_user_id
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
class ConversationChannelClearMessagesResult:
    channel_id: int
    last_deleted: int


@dataclass
class MessageHistoryResult:
    messages: list[dict[str, Any]] = field(default_factory=list)
    channel_id: int = 0


@dataclass
class MessageSendResult:
    """Return value from injecting a synthetic inbound user ``UnifiedMessage``."""

    message_id: str
    channel_id: int


# Sentinel sender_id stamped on synthetic admin/CLI messages. ``routing.channel``
# is the delivery sink (``MANDATORY_CHANNEL_NAME``); ``routing.metadata.origin``
# preserves the source label for downstream filtering.
SYNTHETIC_ADMIN_SENDER_ID = "admin"
SYNTHETIC_ADMIN_ORIGIN = "admin"


class MessageSendTool(Tool):
    """Enqueue a workspace-owner user message via ``InboundPipeline.receive`` (live server only)."""

    runtime = True
    name = "message_send"
    description = (
        "Send a text or audio message into a conversation channel as the workspace owner user. "
        "Requires the Hiro workspace server to be running (in-process ToolRegistry runtime)."
    )
    params = {
        "channel_id": ToolParam(int, "Conversation channel id"),
        "text": ToolParam(str, "UTF-8 body; use exactly one of text, audio_path, audio_base64", required=False),
        "audio_path": ToolParam(str, "Server-local audio file path (CLI)", required=False),
        "audio_base64": ToolParam(str, "Base64-encoded audio bytes (browser / admin UI)", required=False),
        "audio_mime_type": ToolParam(str, "e.g. audio/webm, audio/m4a (required with audio)", required=False),
        "audio_duration_ms": ToolParam(int, "Recorded duration in ms (required with audio)", required=False),
        "request_voice_reply": ToolParam(bool, "Set routing.metadata.request_voice_reply when true", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        # Reason: runtime-scoped tools need the server's CommunicationManager; set on register.
        self._runtime = ctx

    def execute(self, **kwargs: Any) -> MessageSendResult:
        raise RuntimeError(
            "message_send is async-only — use POST /invoke on the Hiro server "
            "or ToolRegistry.invoke_async(); offline CLI forwards via HTTP.",
        )

    async def execute_async(
        self,
        channel_id: int,
        workspace: str | None = None,
        *,
        workspace_path: Path | None = None,
        text: str | None = None,
        audio_path: str | None = None,
        audio_base64: str | None = None,
        audio_mime_type: str | None = None,
        audio_duration_ms: int | None = None,
        request_voice_reply: bool = False,
    ) -> MessageSendResult:
        rt = getattr(self, "_runtime", None)
        if rt is None:
            raise RuntimeError(
                "message_send has no runtime context — register tools with ToolRegistry(runtime=…).",
            )

        # Use the running server's workspace only: a single Hiro process owns one DB + CommManager pair.
        resolved_workspace_path = rt.comm_manager.ctx.workspace_path.resolve()
        if workspace_path is not None:
            explicit = Path(workspace_path).expanduser().resolve()
            if explicit != resolved_workspace_path:
                raise ValueError(
                    "workspace_path does not match this server's workspace filesystem root.",
                )
        elif workspace is not None:
            ws_entry, _ = resolve_workspace(workspace)
            caller_path = Path(ws_entry.path).resolve()
            if caller_path != resolved_workspace_path:
                raise ValueError(
                    "workspace parameter does not match this server's workspace — "
                    f"started on {resolved_workspace_path}, caller asked for {caller_path}.",
                )

        owner_id = get_default_user_id(resolved_workspace_path)
        channel_row = _get_channel_by_id(resolved_workspace_path, channel_id)
        if channel_row is None:
            raise ValueError(f"Conversation channel id {channel_id} not found.")
        if channel_row.user_id != owner_id:
            raise ValueError("Channel does not belong to the workspace owner user.")
        del owner_id  # only used for the ownership check; sender_id is the synthetic sentinel.

        text_ok = bool(text and str(text).strip())
        path_ok = bool(audio_path and str(audio_path).strip())
        b64_ok = bool(audio_base64 and str(audio_base64).strip())
        if int(text_ok) + int(path_ok) + int(b64_ok) != 1:
            raise ValueError("Provide exactly one of: text, audio_path, or audio_base64.")

        if path_ok or b64_ok:
            if not audio_mime_type or not str(audio_mime_type).strip():
                raise ValueError("audio_mime_type is required for audio messages.")
            if audio_duration_ms is None or int(audio_duration_ms) < 0:
                raise ValueError("audio_duration_ms is required and must be non-negative for audio messages.")

        if text_ok:
            items = [ContentItem(content_type="text", body=str(text).strip())]
        else:
            if path_ok:
                p = Path(str(audio_path).strip()).expanduser().resolve()
                if not p.is_file():
                    raise ValueError(f"Audio file not found: {p}")
                raw = p.read_bytes()
            else:
                try:
                    raw = base64.b64decode(str(audio_base64).strip(), validate=False)
                except Exception as exc:
                    raise ValueError("Invalid audio_base64 payload.") from exc
            if not raw:
                raise ValueError("Audio payload is empty.")
            bid = blob_id_for_bytes(raw)
            chunk_size = DEFAULT_CHUNK_SIZE
            chunk_count = chunk_count_for_size(len(raw), chunk_size)
            body_b64 = base64.b64encode(raw).decode("ascii")
            items = [
                ContentItem(
                    content_type="audio",
                    body=body_b64,
                    metadata={
                        "duration_ms": int(audio_duration_ms),
                        "mime_type": str(audio_mime_type).strip(),
                        "blob_id": bid,
                        "size": len(raw),
                        "chunk_size": chunk_size,
                        "chunk_count": chunk_count,
                    },
                ),
            ]

        meta: dict[str, Any] = {
            "chat_channel_id": channel_id,
            # Source label so logs / future filters can tell admin/CLI sends apart
            # from device-originated traffic. Delivery sink is ``routing.channel``.
            "origin": SYNTHETIC_ADMIN_ORIGIN,
        }
        if request_voice_reply:
            meta["request_voice_reply"] = True

        msg_id = str(uuid.uuid4())
        envelope = UnifiedMessage(
            message_type=MESSAGE_TYPE_MESSAGE,
            routing=MessageRouting(
                id=msg_id,
                # ``routing.channel`` is read by ``OutboundPipeline`` as the sink
                # name. Use the mandatory devices channel so the ack + agent reply
                # fan out to all paired devices live, just like a real device send.
                channel=MANDATORY_CHANNEL_NAME,
                direction="inbound",
                sender_id=SYNTHETIC_ADMIN_SENDER_ID,
                metadata=meta,
            ),
            content=items,
        )

        payload = envelope.model_dump(mode="json")
        # await_message_flow=True so persistence + agent enqueue finish before we
        # return — the Admin UI's immediate /messages refresh then sees the row.
        await rt.comm_manager.receive(payload, await_message_flow=True)
        return MessageSendResult(message_id=msg_id, channel_id=channel_id)


class ConversationChannelListTool(Tool):
    name = "conversation_channel_list"
    description = "List all conversation channels (active conversations) and their metadata"
    params = {
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(
        self,
        workspace: str | None = None,
        *,
        workspace_path: Path | None = None,
    ) -> ConversationChannelListResult:
        resolved_workspace_path = workspace_path or _resolve_path(workspace)
        channels = build_channel_list_entries(resolved_workspace_path)
        return ConversationChannelListResult(
            channels=[ch.model_dump(mode="json") for ch in channels],
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
    description = (
        "Create a direct conversation channel for the workspace owner user and selected character slug"
    )
    params = {
        "channel_name": ToolParam(str, "Channel name"),
        "character_id": ToolParam(str, "Character id (slug) for this conversation"),
        "channel_description": ToolParam(str, "Optional description", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(
        self,
        channel_name: str,
        character_id: str,
        channel_description: str = "",
        workspace: str | None = None,
        *,
        workspace_path: Path | None = None,
    ) -> ConversationChannelCreateResult:
        resolved_workspace_path = workspace_path or _resolve_path(workspace)
        channel = create_channel(
            resolved_workspace_path,
            name=channel_name,
            character_id=character_id,
            description=channel_description.strip(),
        )
        return ConversationChannelCreateResult(channel=channel.model_dump())


class ConversationChannelUpdateTool(Tool):
    name = "conversation_channel_update"
    description = (
        "Update an existing conversation channel name, optional description text, "
        "or character slug — type stays direct and owner stays the workspace default user"
    )
    params = {
        "channel_id": ToolParam(int, "Channel integer id"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
        "channel_name": ToolParam(str, "Channel display name", required=False),
        "channel_description": ToolParam(str, "Channel description/subtitle text", required=False),
        "character_id": ToolParam(str, "Character id (slug)", required=False),
    }

    def execute(
        self,
        channel_id: int,
        workspace: str | None = None,
        *,
        workspace_path: Path | None = None,
        channel_name: str | None = None,
        channel_description: str | None = None,
        character_id: str | None = None,
    ) -> ConversationChannelUpdateResult:
        if channel_name is None and channel_description is None and character_id is None:
            raise ValueError(
                "At least one of channel_name, channel_description, or character_id must be provided."
            )
        resolved = workspace_path or _resolve_path(workspace)
        channel = update_channel(
            resolved,
            channel_id,
            name=channel_name,
            description=channel_description,
            character_id=character_id,
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


class ConversationChannelClearMessagesTool(Tool):
    name = "conversation_channel_clear_messages"
    description = (
        "Delete all messages and attachments in a conversation channel (channel row unchanged). "
        "Increments last_deleted on the channel for device sync."
    )
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
    ) -> ConversationChannelClearMessagesResult:
        resolved = workspace_path or _resolve_path(workspace)
        new_epoch = clear_channel_messages(resolved, channel_id)
        return ConversationChannelClearMessagesResult(
            channel_id=channel_id,
            last_deleted=new_epoch,
        )


class MessageHistoryTool(Tool):
    name = "message_history"
    description = (
        "Retrieve normalized message history for a conversation channel. "
        "Use all_messages=true for no row limit; otherwise limit defaults to 50. "
        "Pass after_id alongside after for stable pagination across rows that "
        "share the same created_at timestamp."
    )
    params = {
        "channel_id": ToolParam(int, "Channel integer id"),
        "after": ToolParam(str, "ISO 8601 timestamp - return only messages after this time", required=False),
        "after_id": ToolParam(
            str,
            "External message id tiebreaker for rows sharing ``after`` timestamp",
            required=False,
        ),
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
        *,
        workspace_path: Path | None = None,
        after_id: str | None = None,
    ) -> MessageHistoryResult:
        # ``_sync_history`` is synchronous and meant for asyncio.to_thread, but
        # this tool's callers (CLI, Admin UI) are synchronous too — using the
        # private helper directly here keeps the call chain non-async.
        from ..domain.message_store import _sync_history

        resolved_workspace_path = workspace_path or _resolve_path(workspace)
        eff_limit: int | None = None if all_messages else limit
        messages = _sync_history(
            resolved_workspace_path,
            channel_id,
            after=after,
            after_id=after_id,
            limit=eff_limit,
        )
        return MessageHistoryResult(messages=messages, channel_id=channel_id)
