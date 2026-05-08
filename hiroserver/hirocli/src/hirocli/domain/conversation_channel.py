"""Conversation channel storage helpers for the data.db channels table."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from pydantic import BaseModel

from hiro_commons.timestamps import utc_iso, utc_now

from .data_store import data_db_path, ensure_data_db, get_default_user_id
from .conversation_channel_photo import remove_channel_photo_dir
from .events import DomainEvent, DomainEventType, get_domain_event_bus

logger = logging.getLogger(__name__)


def _notify_channel_changed(workspace_path: Path, channel_id: int) -> None:
    """Publish a channel mutation (create/update/delete or thumbnail change)."""
    get_domain_event_bus().publish(
        DomainEvent(
            type=DomainEventType.CHANNEL_CHANGED,
            workspace_path=workspace_path,
            payload={"channel_id": channel_id},
        )
    )


def notify_conversation_channel_changed(workspace_path: Path, channel_id: int) -> None:
    """Subscriber hook for thumbnails and other extras that alter ``channels.list`` payloads."""
    _notify_channel_changed(workspace_path, channel_id)


class ConversationChannel(BaseModel):
    """Metadata for a single conversation thread."""

    id: int
    name: str
    type: str = "direct"
    character_id: str
    user_id: int
    description: str = ""
    created_at: str
    last_message_at: str | None = None


# Keep the default channel name aligned with data_store.py seeding.
DEFAULT_CONVERSATION_CHANNEL_NAME = "General"


def min_channel_id(workspace_path: Path) -> int | None:
    """Smallest channel primary key in the workspace, if any."""
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        row = conn.execute("SELECT MIN(id) FROM channels").fetchone()
        return int(row[0]) if row and row[0] is not None else None


def _list_channels(workspace_path: Path) -> list[ConversationChannel]:
    """Return all channels ordered by most-recently-active first."""
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM channels
            ORDER BY COALESCE(last_message_at, created_at) DESC
            """
        ).fetchall()
        return [_row_to_channel(row) for row in rows]


def _get_channel_by_id(
    workspace_path: Path,
    channel_id: int,
) -> ConversationChannel | None:
    """Return a channel by id, or None if not found."""
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM channels WHERE id = ?",
            (channel_id,),
        ).fetchone()
        return _row_to_channel(row) if row else None


def _get_channel_by_name(
    workspace_path: Path,
    name: str,
    *,
    user_id: int,
) -> ConversationChannel | None:
    """Return a user-scoped channel by exact name, or None if not found."""
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM channels WHERE user_id = ? AND name = ?",
            (user_id, name),
        ).fetchone()
        return _row_to_channel(row) if row else None


def _get_default_channel(
    workspace_path: Path,
    *,
    user_id: int | None = None,
) -> ConversationChannel | None:
    """Return the seeded default channel, optionally scoped to a user."""
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        if user_id is not None:
            row = conn.execute(
                """
                SELECT * FROM channels
                WHERE user_id = ? AND LOWER(name) = LOWER(?)
                ORDER BY id ASC
                LIMIT 1
                """,
                (user_id, DEFAULT_CONVERSATION_CHANNEL_NAME),
            ).fetchone()
            if row:
                return _row_to_channel(row)

        row = conn.execute(
            """
            SELECT * FROM channels
            WHERE LOWER(name) = LOWER(?)
            ORDER BY id ASC
            LIMIT 1
            """,
            (DEFAULT_CONVERSATION_CHANNEL_NAME,),
        ).fetchone()
        return _row_to_channel(row) if row else None


def update_last_message_at(
    workspace_path: Path,
    channel_id: int,
    ts: str | None = None,
) -> None:
    """Stamp last_message_at on a channel row (defaults to now)."""
    ensure_data_db(workspace_path)
    timestamp = ts or utc_iso(utc_now())
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.execute(
            "UPDATE channels SET last_message_at = ? WHERE id = ?",
            (timestamp, channel_id),
        )
        conn.commit()


def create_channel(
    workspace_path: Path,
    *,
    name: str,
    character_id: str,
    user_id: int | None = None,
    channel_type: str = "direct",
    description: str = "",
    created_at: str | None = None,
) -> ConversationChannel:
    """Create a conversation channel for the workspace default user (single-user mode).

    ``user_id`` is accepted for backwards compatibility but ignored; the seeded owner is always used.
    """
    _ = user_id  # Single-user workspaces: binding is always ``get_default_user_id``.
    uid = get_default_user_id(workspace_path)
    channel_type = "direct"
    ensure_data_db(workspace_path)
    timestamp = created_at or utc_iso(utc_now())
    desc = (description or "").strip()
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT * FROM channels WHERE user_id = ? AND name = ?",
            (uid, name),
        ).fetchone()
        if existing is not None:
            raise ValueError(f"Conversation channel '{name}' already exists for user {uid}.")

        cursor = conn.execute(
            """
            INSERT INTO channels (name, type, character_id, user_id, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, channel_type, character_id, uid, desc, timestamp),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM channels WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Conversation channel creation succeeded but row could not be reloaded.")
        created = _row_to_channel(row)
        _notify_channel_changed(workspace_path, created.id)
        return created


def update_channel(
    workspace_path: Path,
    channel_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
    character_id: str | None = None,
) -> ConversationChannel:
    """Update name, optional description text, or character slug; ``type``/``user_id`` stay fixed."""
    existing = _get_channel_by_id(workspace_path, channel_id)
    if existing is None:
        raise ValueError(f"No conversation channel with id {channel_id}.")

    new_name = name if name is not None else existing.name
    new_character = character_id if character_id is not None else existing.character_id
    new_desc = existing.description if description is None else description.strip()

    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        if (existing.user_id, new_name) != (existing.user_id, existing.name):
            conflict = conn.execute(
                "SELECT id FROM channels WHERE user_id = ? AND name = ? AND id != ?",
                (existing.user_id, new_name, channel_id),
            ).fetchone()
            if conflict is not None:
                raise ValueError(
                    f"Conversation channel '{new_name}' already exists for user {existing.user_id}."
                )

        conn.execute(
            """
            UPDATE channels
            SET name = ?, character_id = ?, description = ?
            WHERE id = ?
            """,
            (new_name, new_character, new_desc, channel_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM channels WHERE id = ?", (channel_id,)).fetchone()
        if row is None:
            raise RuntimeError("Conversation channel update succeeded but row could not be reloaded.")
        updated = _row_to_channel(row)
        _notify_channel_changed(workspace_path, updated.id)
        return updated


def delete_channel(workspace_path: Path, channel_id: int) -> None:
    """Remove a conversation channel and all of its messages (FK-safe).

    Raises if ``channel_id`` is the smallest id in the table (primary/default channel guard).
    """
    if _get_channel_by_id(workspace_path, channel_id) is None:
        raise ValueError(f"No conversation channel with id {channel_id}.")

    anchor = min_channel_id(workspace_path)
    if anchor is not None and channel_id == anchor:
        raise ValueError("Cannot delete the primary conversation channel (lowest channel id).")

    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.execute(
            """
            DELETE FROM message_attachments
            WHERE message_pk IN (
                SELECT id FROM messages WHERE channel_id = ?
            )
            """,
            (channel_id,),
        )
        conn.execute("DELETE FROM messages WHERE channel_id = ?", (channel_id,))
        conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        conn.commit()
    remove_channel_photo_dir(workspace_path, channel_id)
    _notify_channel_changed(workspace_path, channel_id)


def _row_to_channel(row: sqlite3.Row) -> ConversationChannel:
    keys = row.keys()
    raw_desc = str(row["description"]) if "description" in keys else ""
    return ConversationChannel(
        id=row["id"],
        name=row["name"],
        type=row["type"],
        character_id=row["character_id"],
        user_id=row["user_id"],
        description=raw_desc.strip(),
        created_at=row["created_at"],
        last_message_at=row["last_message_at"],
    )
