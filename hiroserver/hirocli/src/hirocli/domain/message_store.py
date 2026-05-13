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

from .blob_store import DEFAULT_CHUNK_SIZE, chunk_count_for_size
from .data_store import data_db_path, ensure_data_db
from .media_store import audio_extension_for_media_type
from .message_attachments import attachment_ref

log = Logger.get("MSG_STORE")


# ---------------------------------------------------------------------------
# High-level persistence entry points
# ---------------------------------------------------------------------------


async def persist_inbound(workspace_path: Path, msg: UnifiedMessage) -> int:
    """Persist an enriched inbound UnifiedMessage to data.db + media files.

    Returns the message integer PK. Resolves the conversation
    channel, extracts text from enriched content items, and saves any binary
    media to disk.
    """
    from .conversation_channel import (
        resolve_chat_channel_from_metadata,
        update_last_message_at,
    )
    from .blob_store import blob_id_for_file
    from .data_store import data_dir
    from .media_store import decode_and_save
    from .message_attachments import insert_attachment

    # Transport channel is not the conversation. The device/admin supplies the
    # target conversation in routing.metadata.chat_channel_id.
    chat_channel = resolve_chat_channel_from_metadata(
        workspace_path,
        msg.routing.metadata,
    )
    channel_id = int(chat_channel.id)
    channel_user_id = chat_channel.user_id

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

    # ``messages.metadata`` no longer mirrors per-item attachment metadata —
    # attachments live in their own table and are joined back in by
    # _sync_history. Keeping content_items here would double-store every
    # blob_id / mime / size pair we already write to message_attachments.
    message_pk = await save_message(
        workspace_path,
        external_id=msg.routing.id,
        channel_id=channel_id,
        user_id=channel_user_id,
        sender_type="user",
        sender_id=msg.routing.sender_id,
        content_type=primary_content_type,
        body=text_body,
    )

    for slot_index, item in enumerate(msg.content):
        if item.content_type != CONTENT_TYPE_AUDIO:
            continue
        if not item.body:
            log.warning(
                "⚠️ Audio attachment skipped — inbound · empty_body",
                slot_index=slot_index,
                msg_id=msg.routing.id,
            )
            continue
        if item.body.startswith(("http://", "https://")):
            log.info(
                "⬇️ Audio attachment skipped — inbound · external_url",
                slot_index=slot_index,
                msg_id=msg.routing.id,
            )
            continue

        mime = str(item.metadata.get("mime_type", "audio/m4a") or "audio/m4a")
        ext = audio_extension_for_media_type(mime)
        try:
            media_path = decode_and_save(
                workspace_path,
                channel_id,
                message_pk,
                item.body,
                ext,
                slot_index=slot_index,
            )
        except (ValueError, OSError) as exc:
            # Surface decode/IO problems instead of silently dropping the row.
            log.error(
                "❌ Audio attachment decode failed — inbound · audio",
                error=str(exc),
                slot_index=slot_index,
                msg_id=msg.routing.id,
                exc_info=True,
            )
            continue

        abs_path = data_dir(workspace_path) / media_path
        blob_id = blob_id_for_file(abs_path)
        size = abs_path.stat().st_size
        duration_raw = item.metadata.get("duration_ms")
        duration_ms = (
            int(duration_raw) if isinstance(duration_raw, (int, float)) else None
        )
        attachment_metadata: dict[str, Any] = {"source": "user_audio"}
        transcript = item.metadata.get("description")
        if isinstance(transcript, str):
            attachment_metadata["transcript"] = transcript
        await asyncio.to_thread(
            insert_attachment,
            workspace_path,
            message_pk=message_pk,
            slot_index=slot_index,
            content_type=item.content_type,
            blob_id=blob_id,
            media_type=mime,
            size=size,
            media_path=media_path,
            filename=abs_path.name,
            duration_ms=duration_ms,
            metadata=attachment_metadata,
        )
        log.info(
            "⬇️ Audio attachment stored — inbound · audio",
            blob_id=blob_id,
            size=size,
            duration_ms=duration_ms,
            slot_index=slot_index,
            msg_id=msg.routing.id,
        )

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
        metadata=metadata,
        created_at=created_at,
    )


async def update_message_body(
    workspace_path: Path,
    message_pk: int,
    body: str,
) -> None:
    """Replace a persisted message's text body in-place.

    Used after speech-to-text completes for an inbound audio message: the
    ingest subscriber writes the row first (so the live mirror has a stable
    id), then this function fills in the transcript so history reload (admin
    UI / cold device) sees the full text.
    """
    await asyncio.to_thread(_sync_update_body, workspace_path, message_pk, body)


async def patch_message_metadata(
    workspace_path: Path,
    message_pk: int,
    patch: dict[str, Any],
) -> None:
    """Merge top-level keys into ``messages.metadata`` without touching others."""
    await asyncio.to_thread(_sync_patch_metadata, workspace_path, message_pk, patch)


def _sync_update_body(
    workspace_path: Path,
    message_pk: int,
    body: str,
) -> None:
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.execute(
            "UPDATE messages SET body = ? WHERE id = ?",
            (body, message_pk),
        )
        conn.commit()


def _sync_patch_metadata(
    workspace_path: Path,
    message_pk: int,
    patch: dict[str, Any],
) -> None:
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        row = conn.execute(
            "SELECT metadata FROM messages WHERE id = ?",
            (message_pk,),
        ).fetchone()
        if row is None:
            return
        try:
            current = json.loads(row[0] or "{}")
        except (json.JSONDecodeError, TypeError):
            current = {}
        if not isinstance(current, dict):
            current = {}
        current.update(patch)
        conn.execute(
            "UPDATE messages SET metadata = ? WHERE id = ?",
            (
                json.dumps(current, ensure_ascii=False, separators=(",", ":")),
                message_pk,
            ),
        )
        conn.commit()


async def list_messages(
    workspace_path: Path,
    channel_id: int,
    *,
    after: str | None = None,
    after_id: str | None = None,
    limit: int | None = 50,
) -> list[dict[str, Any]]:
    """Return messages for a channel, optionally after a timestamp, oldest first.

    ``limit`` None means no cap (all matching rows). Default 50.
    """
    return await asyncio.to_thread(
        _sync_list,
        workspace_path,
        channel_id,
        after=after,
        after_id=after_id,
        limit=limit,
    )


async def list_message_history(
    workspace_path: Path,
    channel_id: int,
    *,
    after: str | None = None,
    after_id: str | None = None,
    limit: int | None = 50,
) -> list[dict[str, Any]]:
    """Return normalized history messages for device reload."""
    return await asyncio.to_thread(
        _sync_history,
        workspace_path,
        channel_id,
        after=after,
        after_id=after_id,
        limit=limit,
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
                 content_type, body, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (external_id, channel_id, user_id, sender_type, sender_id,
             content_type, body, meta_json, ts),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]


def _sync_list(
    workspace_path: Path,
    channel_id: int,
    *,
    after: str | None = None,
    after_id: str | None = None,
    limit: int | None = 50,
) -> list[dict[str, Any]]:
    """List messages oldest-first. ``limit`` None omits SQL LIMIT (all rows).

    Ordering is ``(created_at, external_id)`` so the device can resume from a
    compound cursor — without ``external_id`` as a tiebreaker, multiple rows
    sharing the same ISO timestamp would silently lose ones at the page
    boundary on the next pull.
    """
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        order_clause = "ORDER BY created_at ASC, external_id ASC"
        if after and after_id:
            # Strict lexicographic > on (created_at, external_id). Rows with
            # the same created_at but a larger external_id are still returned.
            where = (
                "WHERE channel_id = ? AND "
                "(created_at > ? OR (created_at = ? AND external_id > ?))"
            )
            params: tuple[Any, ...] = (channel_id, after, after, after_id)
        elif after:
            where = "WHERE channel_id = ? AND created_at > ?"
            params = (channel_id, after)
        else:
            where = "WHERE channel_id = ?"
            params = (channel_id,)

        if limit is None:
            sql = f"SELECT * FROM messages {where} {order_clause}"
            rows = conn.execute(sql, params).fetchall()
        else:
            sql = f"SELECT * FROM messages {where} {order_clause} LIMIT ?"
            rows = conn.execute(sql, (*params, limit)).fetchall()

        return [_row_to_dict(row) for row in rows]


def _sync_history(
    workspace_path: Path,
    channel_id: int,
    *,
    after: str | None = None,
    after_id: str | None = None,
    limit: int | None = 50,
) -> list[dict[str, Any]]:
    """List messages in the normalized history contract."""
    messages = _sync_list(
        workspace_path,
        channel_id,
        after=after,
        after_id=after_id,
        limit=limit,
    )
    if not messages:
        return []

    message_pks = [int(row["id"]) for row in messages]
    placeholders = ",".join("?" for _ in message_pks)
    attachments_by_message: dict[int, list[dict[str, Any]]] = {
        pk: [] for pk in message_pks
    }
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT *
            FROM message_attachments
            WHERE message_pk IN ({placeholders})
            ORDER BY message_pk ASC, slot_index ASC
            """,
            message_pks,
        ).fetchall()
    for row in rows:
        attachment = _attachment_row_to_dict(row)
        attachments_by_message.setdefault(int(attachment["message_pk"]), []).append(
            attachment
        )

    return [
        _history_row(row, attachments_by_message.get(int(row["id"]), []))
        for row in messages
    ]


def _history_row(
    row: dict[str, Any],
    attachments: list[dict[str, Any]],
) -> dict[str, Any]:
    message_id = str(row["external_id"])
    content: list[dict[str, Any]] = []
    body = str(row.get("body") or "")
    if body.strip():
        content.append({"content_type": CONTENT_TYPE_TEXT, "body": body})

    for attachment in attachments:
        metadata: dict[str, Any] = {}
        existing_meta = attachment.get("metadata")
        if isinstance(existing_meta, dict):
            metadata.update(existing_meta)
        metadata["blob_id"] = attachment["blob_id"]
        metadata["size"] = attachment["size"]
        metadata["media_type"] = attachment["media_type"]
        metadata["chunk_size"] = DEFAULT_CHUNK_SIZE
        metadata["chunk_count"] = chunk_count_for_size(
            int(attachment["size"]),
            DEFAULT_CHUNK_SIZE,
        )
        duration_ms = attachment.get("duration_ms")
        if duration_ms is not None:
            metadata["duration_ms"] = duration_ms

        content.append(
            {
                "content_type": attachment["content_type"],
                "body": attachment_ref(message_id, int(attachment["slot_index"])),
                "metadata": metadata,
            }
        )

    result = {
        "id": message_id,
        # DB PK for admin (e.g. media URLs) — device clients may ignore ``message_pk``.
        "message_pk": int(row["id"]),
        "channel_id": row["channel_id"],
        "sender_type": row["sender_type"],
        "sender_id": row["sender_id"],
        "created_at": row["created_at"],
        "content": content,
    }
    metadata = row.get("metadata")
    if isinstance(metadata, dict) and metadata:
        result["metadata"] = metadata
    return result


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    if d.get("metadata"):
        try:
            d["metadata"] = json.loads(d["metadata"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def _attachment_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    if d.get("metadata"):
        try:
            d["metadata"] = json.loads(d["metadata"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d
