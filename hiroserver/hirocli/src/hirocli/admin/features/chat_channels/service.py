"""Conversation channels and message history operations for the admin API."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from hirocli.domain.conversation_channel import (
    min_channel_id,
    notify_conversation_channel_changed,
)
from hirocli.domain.conversation_channel_photo import (
    read_channel_thumbnail_bytes,
    write_channel_thumbnail_from_file,
)
from hirocli.domain.message_store import _sync_list
from hirocli.domain.workspace import resolve_workspace
from hirocli.tools.conversation import (
    ConversationChannelCreateTool,
    ConversationChannelDeleteTool,
    ConversationChannelListTool,
    ConversationChannelUpdateTool,
)

from hirocli.admin.shared.result import Result

_MAX_INLINE_PHOTO_BYTES = 2_000_000


def _inline_image_data_url(thumb: bytes) -> str:
    if (
        len(thumb) >= 12
        and thumb.startswith(b"RIFF")
        and thumb[8:12] == b"WEBP"
    ):
        mime = "image/webp"
    else:
        mime = "image/png"
    return f"data:{mime};base64,{base64.b64encode(thumb).decode()}"


class ChatChannelsService:
    """Facade over conversation tools with explicit workspace id."""

    def _workspace_path(self, workspace_id: str | None) -> Path | None:
        if not workspace_id:
            return None
        entry, _ = resolve_workspace(workspace_id)
        return Path(entry.path)

    def list_channels(self, workspace_id: str | None) -> Result[list[dict[str, Any]]]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            out = ConversationChannelListTool().execute(workspace=workspace_id)
            wp = self._workspace_path(workspace_id)
            if wp is None:
                return Result.failure("Workspace path could not be resolved.")
            anchor = min_channel_id(wp)
            rows: list[dict[str, Any]] = []
            for row in list(out.channels):
                d = dict(row)
                cid = int(d["id"])
                d["is_lowest_id_channel"] = anchor is not None and cid == anchor
                thumb = read_channel_thumbnail_bytes(wp, cid)
                url = None
                if thumb is not None and len(thumb) <= _MAX_INLINE_PHOTO_BYTES:
                    url = _inline_image_data_url(thumb)
                d["photo_data_url"] = url
                rows.append(d)
            return Result.success(rows)
        except Exception as exc:
            return Result.failure(str(exc))

    def create_channel(
        self,
        workspace_id: str | None,
        *,
        name: str,
        character_id: str,
        description: str = "",
    ) -> Result[dict[str, Any]]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        if not name.strip():
            return Result.failure("Name is required.")
        try:
            out = ConversationChannelCreateTool().execute(
                channel_name=name.strip(),
                character_id=character_id.strip(),
                channel_description=(description or "").strip(),
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
        description: str | None = None,
        character_id: str | None = None,
    ) -> Result[dict[str, Any]]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            out = ConversationChannelUpdateTool().execute(
                channel_id,
                workspace=workspace_id,
                channel_name=name,
                channel_description=description,
                character_id=character_id,
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

    def upload_channel_photo(
        self,
        workspace_id: str | None,
        channel_id: int,
        tmp_image_path: str,
    ) -> Result[None]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        wp = self._workspace_path(workspace_id)
        if wp is None:
            return Result.failure("Workspace path could not be resolved.")
        path = Path(tmp_image_path).expanduser().resolve()
        try:
            write_channel_thumbnail_from_file(wp, channel_id, path)
        except Exception as exc:
            return Result.failure(str(exc))
        notify_conversation_channel_changed(wp, channel_id)
        return Result.success(None)

    def list_messages_all(
        self,
        workspace_id: str | None,
        channel_id: int,
    ) -> Result[list[dict[str, Any]]]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            wp = self._workspace_path(workspace_id)
            if wp is None:
                return Result.failure("Workspace path could not be resolved.")
            messages = _sync_list(wp, channel_id, limit=None)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(messages)
