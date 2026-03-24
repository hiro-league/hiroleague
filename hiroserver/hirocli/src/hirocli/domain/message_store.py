"""Message persistence — CRUD for the messages table in data.db.

All database I/O is synchronous and offloaded via asyncio.to_thread
in the public async wrappers.

The persist_inbound() function is the single entry point for saving
an inbound UnifiedMessage (after adapter enrichment) — called by
CommunicationManager. It resolves the channel, extracts text from
enriched content items, saves media files, and inserts the message row.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from hiro_channel_sdk.constants import CONTENT_TYPE_AUDIO, CONTENT_TYPE_TEXT
from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.log import Logger
from hiro_commons.timestamps import utc_iso, utc_now

from .data_store import data_db_path, ensure_data_db

log = Logger.get("MSG_STORE")


# ---------------------------------------------------------------------------
# High-level persistence entry points
# ---------------------------------------------------------------------------

_MEDIA_EXTENSIONS: dict[str, str] = {CONTENT_TYPE_AUDIO: "m4a"}


async def persist_inbound(workspace_path: Path, msg: UnifiedMessage) -> int:
    """Persist an enriched inbound UnifiedMessage to data.db + media files.

    Returns the message integer PK. Resolves the conversation
    channel, extracts text from enriched content items, and saves any binary
    media to disk.
    """
    from ..tools.conversation import ConversationChannelGetTool
    from .data_store import get_default_user_id
    from .conversation_channel import update_last_message_at
    from .media_store import decode_and_save

    channel_name = f"{msg.routing.channel}:{msg.routing.sender_id}"
    user_id = get_default_user_id(workspace_path)
    channel_result = ConversationChannelGetTool().execute(
        channel_name=channel_name,
        workspace_path=workspace_path,
        user_id=user_id,
    )
    if channel_result.channel is None:
        raise RuntimeError("No conversation channel available for inbound message")
    channel_id = int(channel_result.channel["id"])
    channel_user_id = channel_result.channel.get("user_id")

    body_parts: list[str] = []
    primary_content_type = "text"
    for item in msg.content:
        if item.content_type == CONTENT_TYPE_TEXT:
            body_parts.append(item.body)
        elif "description" in item.metadata:
            body_parts.append(item.metadata["description"])
            primary_content_type = item.content_type
        else:
            primary_content_type = item.content_type

    text_body = "\n".join(body_parts)
    items_meta = [
        {"content_type": item.content_type, "metadata": item.metadata}
        for item in msg.content
    ]

    message_pk = await save_message(
        workspace_path,
        external_id=msg.routing.id,
        channel_id=channel_id,
        user_id=channel_user_id,
        sender_type="user",
        sender_id=msg.routing.sender_id,
        content_type=primary_content_type,
        body=text_body,
        metadata={"content_items": items_meta},
    )

    for item in msg.content:
        ext = _MEDIA_EXTENSIONS.get(item.content_type)
        if ext and item.body and not item.body.startswith(("http://", "https://")):
            mime = item.metadata.get("mime_type", "")
            if "/" in mime:
                ext = mime.split("/")[-1].replace("mpeg", "mp3")
            media_path = decode_and_save(
                workspace_path, channel_id, message_pk, item.body, ext,
            )
            await update_media_path(workspace_path, message_pk, media_path)

    await asyncio.to_thread(update_last_message_at, workspace_path, channel_id)
    return message_pk


# ---------------------------------------------------------------------------
# Async public API
# ---------------------------------------------------------------------------


async def save_message(
    workspace_path: Path,
    *,
    external_id: str,
    channel_id: int,
    user_id: int | None = None,
    sender_type: str,
    sender_id: str,
    content_type: str,
    body: str = "",
    media_path: str | None = None,
    metadata: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> int:
    """Insert a message row and return its integer PK."""
    return await asyncio.to_thread(
        _sync_save,
        workspace_path,
        external_id=external_id,
        channel_id=channel_id,
        user_id=user_id,
        sender_type=sender_type,
        sender_id=sender_id,
        content_type=content_type,
        body=body,
        media_path=media_path,
        metadata=metadata,
        created_at=created_at,
    )


async def update_media_path(
    workspace_path: Path,
    message_pk: int,
    media_path: str,
) -> None:
    """Set media_path on an existing message row (used after saving media files)."""
    await asyncio.to_thread(_sync_update_media_path, workspace_path, message_pk, media_path)


async def list_messages(
    workspace_path: Path,
    channel_id: int,
    *,
    after: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return messages for a channel, optionally after a timestamp, newest last."""
    return await asyncio.to_thread(
        _sync_list, workspace_path, channel_id, after=after, limit=limit
    )


# ---------------------------------------------------------------------------
# Sync helpers (run inside asyncio.to_thread)
# ---------------------------------------------------------------------------


def _sync_save(
    workspace_path: Path,
    *,
    external_id: str,
    channel_id: int,
    user_id: int | None,
    sender_type: str,
    sender_id: str,
    content_type: str,
    body: str,
    media_path: str | None,
    metadata: dict[str, Any] | None,
    created_at: str | None,
) -> int:
    ensure_data_db(workspace_path)
    ts = created_at or utc_iso(utc_now())
    meta_json = json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":"))
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        cursor = conn.execute(
            """
            INSERT INTO messages
                (external_id, channel_id, user_id, sender_type, sender_id,
                 content_type, body, media_path, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (external_id, channel_id, user_id, sender_type, sender_id,
             content_type, body, media_path, meta_json, ts),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]


def _sync_update_media_path(
    workspace_path: Path,
    message_pk: int,
    media_path: str,
) -> None:
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.execute(
            "UPDATE messages SET media_path = ? WHERE id = ?",
            (media_path, message_pk),
        )
        conn.commit()


def _sync_list(
    workspace_path: Path,
    channel_id: int,
    *,
    after: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        if after:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE channel_id = ? AND created_at > ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (channel_id, after, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE channel_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (channel_id, limit),
            ).fetchall()

        return [_row_to_dict(row) for row in rows]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    if d.get("metadata"):
        try:
            d["metadata"] = json.loads(d["metadata"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d
