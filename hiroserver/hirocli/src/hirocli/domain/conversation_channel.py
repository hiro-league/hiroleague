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
    agent_id: str | None = None
    user_id: int | None = None
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
) -> ConversationChannel | None:
    """Return a channel by exact name, or None if not found."""
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM channels WHERE name = ?",
            (name,),
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


def _row_to_channel(row: sqlite3.Row) -> ConversationChannel:
    return ConversationChannel(
        id=row["id"],
        name=row["name"],
        type=row["type"],
        agent_id=row["agent_id"],
        user_id=row["user_id"],
        created_at=row["created_at"],
        last_message_at=row["last_message_at"],
    )
