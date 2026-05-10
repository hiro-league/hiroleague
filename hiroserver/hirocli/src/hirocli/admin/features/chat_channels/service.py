"""Conversation channels and message history operations for the admin API."""

from __future__ import annotations

import base64
import sqlite3
from pathlib import Path
from time import perf_counter
from typing import Any

from hiro_commons.log import Logger

from hirocli.domain.conversation_channel import (
    min_channel_id,
    notify_conversation_channel_changed,
)
from hirocli.domain.conversation_channel_photo import (
    read_channel_thumbnail_bytes,
    write_channel_thumbnail_from_file,
)
from hirocli.domain.data_store import data_db_path, ensure_data_db
from hirocli.domain.files_resolver import resolve_ref
from hirocli.domain.message_attachments import attachment_ref
from hirocli.domain.message_store import _sync_history
from hirocli.domain.workspace import resolve_workspace
from hirocli.domain.workspace_server_client import post_invoke_sync
from hirocli.tools.conversation import (
    ConversationChannelClearMessagesTool,
    ConversationChannelCreateTool,
    ConversationChannelDeleteTool,
    ConversationChannelListTool,
    ConversationChannelUpdateTool,
)

from hirocli.admin.shared.result import Result

_MAX_INLINE_PHOTO_BYTES = 2_000_000

_log = Logger.get("ADMIN.CHANNELS")


def _external_message_id_in_channel(
    workspace_path: Path,
    channel_id: int,
    external_message_id: str,
) -> bool:
    """True when ``external_id`` belongs to ``channel_id`` (admin media authz)."""
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        row = conn.execute(
            """
            SELECT 1 FROM messages
            WHERE external_id = ? AND channel_id = ?
            LIMIT 1
            """,
            (external_message_id, channel_id),
        ).fetchone()
    return row is not None


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

    def clear_messages(self, workspace_id: str | None, channel_id: int) -> Result[dict[str, Any]]:
        """Bulk-delete all messages in the channel (channel row unchanged; bumps ``last_deleted``)."""
        if not workspace_id:
            return Result.failure("No workspace selected.")
        started = perf_counter()
        try:
            out = ConversationChannelClearMessagesTool().execute(
                channel_id, workspace=workspace_id
            )
        except Exception as exc:
            _log.warning(
                "⚠️ Messages clear failed — HiroAdmin · conversation_channel",
                channel_id=channel_id,
                workspace_id=workspace_id,
                error=str(exc),
                exc_info=True,
            )
            return Result.failure(str(exc))
        # Admin HTTP bypasses ``RequestHandler`` — no ``request:channels.clear_messages`` line unless we log here.
        _log.info(
            "✅ Messages cleared — HiroAdmin · conversation_channel",
            channel_id=out.channel_id,
            last_deleted=out.last_deleted,
            workspace_id=workspace_id,
            elapsed_ms=int((perf_counter() - started) * 1000),
        )
        return Result.success(
            {"channel_id": out.channel_id, "last_deleted": out.last_deleted}
        )

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
            # Same normalized ``content[]`` as ``messages.history`` (+ ``message_pk``), not raw ``messages`` rows.
            messages = _sync_history(wp, channel_id, limit=None)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(messages)

    def send_chat_message(
        self,
        workspace_id: str | None,
        channel_id: int,
        *,
        text: str | None = None,
        audio_base64: str | None = None,
        audio_mime_type: str | None = None,
        audio_duration_ms: int | None = None,
        request_voice_reply: bool = False,
    ) -> Result[dict[str, Any]]:
        """Deliver a synthetic user message through the workspace server's ``InboundPipeline``."""
        if not workspace_id:
            return Result.failure("No workspace selected.")

        wp = self._workspace_path(workspace_id)
        if wp is None:
            return Result.failure("Workspace path could not be resolved.")

        text_ok = bool(text and str(text).strip())
        b64_ok = bool(audio_base64 and str(audio_base64).strip())
        if int(text_ok) + int(b64_ok) != 1:
            return Result.failure("Provide exactly one of text or audio_base64.")
        params: dict[str, Any] = {
            "channel_id": channel_id,
            "request_voice_reply": request_voice_reply,
            "workspace": workspace_id,
        }
        if text_ok:
            params["text"] = str(text).strip()
        else:
            if audio_mime_type is None or not str(audio_mime_type).strip():
                return Result.failure("audio_mime_type is required with audio.")
            if audio_duration_ms is None or int(audio_duration_ms) < 0:
                return Result.failure("audio_duration_ms is required with audio.")
            params["audio_base64"] = str(audio_base64).strip()
            params["audio_mime_type"] = str(audio_mime_type).strip()
            params["audio_duration_ms"] = int(audio_duration_ms)

        started = perf_counter()
        try:
            out = post_invoke_sync(wp, "message_send", params)
        except Exception as exc:
            _log.warning(
                "⚠️ Chat message send failed — HiroAdmin · message_send proxy",
                channel_id=channel_id,
                workspace_id=workspace_id,
                error=str(exc),
                exc_info=True,
            )
            return Result.failure(str(exc))

        _log.info(
            "✅ Chat message sent — HiroAdmin · message_send proxy",
            channel_id=channel_id,
            message_id=out.get("message_id"),
            workspace_id=workspace_id,
            elapsed_ms=int((perf_counter() - started) * 1000),
        )
        return Result.success(out)

    def resolve_message_attachment_media(
        self,
        workspace_id: str | None,
        channel_id: int,
        external_message_id: str,
        slot_index: int,
    ) -> Result[tuple[str, str]]:
        """Resolve attachment file path and MIME for admin playback.

        Returns ``(absolute_path_str, media_type)`` or failure (not found /
        unresolved).
        """
        if not workspace_id:
            return Result.failure("No workspace selected.")
        wp = self._workspace_path(workspace_id)
        if wp is None:
            return Result.failure("Workspace path could not be resolved.")
        try:
            if not _external_message_id_in_channel(wp, channel_id, external_message_id):
                return Result.failure("Message not found in channel.")
            ref = attachment_ref(external_message_id.strip(), slot_index)
            path, media_type, _blob = resolve_ref(
                wp,
                ref,
                requesting_device_id=None,
            )
        except FileNotFoundError as exc:
            return Result.failure(str(exc))
        except (PermissionError, ValueError, OSError) as exc:
            return Result.failure(str(exc))
        return Result.success((str(path), media_type))
