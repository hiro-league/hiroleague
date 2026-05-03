"""Conversation channel storage helpers for the data.db channels table."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pydantic import BaseModel

from hiro_commons.timestamps import utc_iso, utc_now

from .data_store import data_db_path, ensure_data_db


class ConversationChannel(BaseModel):
    """Metadata for a single conversation thread."""

    id: int
    name: str
    type: str = "direct"
    character_id: str
    user_id: int
    created_at: str
    last_message_at: str | None = None


# Keep the default channel name aligned with data_store.py seeding.
DEFAULT_CONVERSATION_CHANNEL_NAME = "General"


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
    user_id: int,
    channel_type: str = "direct",
    created_at: str | None = None,
) -> ConversationChannel:
    """Create a new conversation channel scoped to a user."""
    ensure_data_db(workspace_path)
    timestamp = created_at or utc_iso(utc_now())
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT * FROM channels WHERE user_id = ? AND name = ?",
            (user_id, name),
        ).fetchone()
        if existing is not None:
            raise ValueError(f"Conversation channel '{name}' already exists for user {user_id}.")

        cursor = conn.execute(
            """
            INSERT INTO channels (name, type, character_id, user_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, channel_type, character_id, user_id, timestamp),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM channels WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Conversation channel creation succeeded but row could not be reloaded.")
        return _row_to_channel(row)


def update_channel(
    workspace_path: Path,
    channel_id: int,
    *,
    name: str | None = None,
    channel_type: str | None = None,
    character_id: str | None = None,
    user_id: int | None = None,
) -> ConversationChannel:
    """Update editable fields on a conversation channel row.

    Enforces unique (user_id, name) per workspace when name or user_id changes.
    """
    existing = _get_channel_by_id(workspace_path, channel_id)
    if existing is None:
        raise ValueError(f"No conversation channel with id {channel_id}.")

    new_name = name if name is not None else existing.name
    new_type = channel_type if channel_type is not None else existing.type
    new_character = character_id if character_id is not None else existing.character_id
    new_user = user_id if user_id is not None else existing.user_id

    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        if (new_user, new_name) != (existing.user_id, existing.name):
            conflict = conn.execute(
                "SELECT id FROM channels WHERE user_id = ? AND name = ? AND id != ?",
                (new_user, new_name, channel_id),
            ).fetchone()
            if conflict is not None:
                raise ValueError(
                    f"Conversation channel '{new_name}' already exists for user {new_user}."
                )

        conn.execute(
            """
            UPDATE channels
            SET name = ?, type = ?, character_id = ?, user_id = ?
            WHERE id = ?
            """,
            (new_name, new_type, new_character, new_user, channel_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM channels WHERE id = ?", (channel_id,)).fetchone()
        if row is None:
            raise RuntimeError("Conversation channel update succeeded but row could not be reloaded.")
        return _row_to_channel(row)


def delete_channel(workspace_path: Path, channel_id: int) -> None:
    """Remove a conversation channel and all of its messages (FK-safe)."""
    if _get_channel_by_id(workspace_path, channel_id) is None:
        raise ValueError(f"No conversation channel with id {channel_id}.")

    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.execute("DELETE FROM messages WHERE channel_id = ?", (channel_id,))
        conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        conn.commit()


def _row_to_channel(row: sqlite3.Row) -> ConversationChannel:
    return ConversationChannel(
        id=row["id"],
        name=row["name"],
        type=row["type"],
        character_id=row["character_id"],
        user_id=row["user_id"],
        created_at=row["created_at"],
        last_message_at=row["last_message_at"],
    )
