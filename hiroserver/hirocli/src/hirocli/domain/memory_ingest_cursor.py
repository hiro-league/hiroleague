"""Per-conversation memory-ingestion watermark (``memory_ingest_cursors`` in data.db).

Windowed batch ingestion (docs/memory-eval-vs-chat-parity.md → "Ingestion — implementation
design"): chat accumulates N exchanges and ingests them as ONE two-speaker memory episode. This
cursor marks the last message (by ``external_id``) that has been folded into long-term memory for
a conversation channel, so the batching controller can read only the *pending* turns
(``message_store.list_messages(after_id=...)``) and advance the watermark past exactly what it
ingested — never re-ingesting a turn.

The store holds only a position, NOT the window size N — so changing ``memory.extraction.*`` prefs
mid-conversation is safe (the controller re-reads N each turn; the cursor is N-independent).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger
from hiro_commons.timestamps import utc_iso, utc_now

from .data_store import data_db_path, ensure_data_db

log = Logger.get("DATA_STORE.MEMORY_CURSOR")


def get_cursor(workspace_path: Path, channel_id: int) -> dict[str, Any] | None:
    """Return ``{"last_ingested_id", "last_ingested_at"}`` for a channel, or ``None`` when no
    turn has been ingested yet (a fresh conversation, or one that predates windowed ingestion)."""
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT last_ingested_id, last_ingested_at FROM memory_ingest_cursors "
            "WHERE channel_id = ?",
            (int(channel_id),),
        ).fetchone()
    return dict(row) if row is not None else None


def advance_cursor(
    workspace_path: Path,
    channel_id: int,
    *,
    last_ingested_id: str,
    last_ingested_at: str,
) -> None:
    """Move the watermark to ``last_ingested_id`` (the ``external_id`` of the newest message just
    folded into memory) and record its ``created_at`` (``last_ingested_at``, used by the idle
    sweep). Upsert — one row per channel. Advancing only ever happens AFTER a successful ingest, so
    a crash mid-ingest leaves the cursor where it was and the window is retried, never skipped."""
    ensure_data_db(workspace_path)
    now = utc_iso(utc_now())
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.execute(
            """
            INSERT INTO memory_ingest_cursors
                (channel_id, last_ingested_id, last_ingested_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                last_ingested_id = excluded.last_ingested_id,
                last_ingested_at = excluded.last_ingested_at,
                updated_at       = excluded.updated_at
            """,
            (int(channel_id), str(last_ingested_id), str(last_ingested_at), now),
        )
        conn.commit()
    log.info(
        "✅ memory cursor — advanced · channel=%s · last=%s",
        channel_id,
        last_ingested_id,
    )


def list_idle_pending_channels(workspace_path: Path, *, idle_before: str) -> list[int]:
    """Channel ids whose NEWEST message is older than ``idle_before`` (the conversation has gone
    idle) yet newer than the memory watermark (turns are still pending) — the idle-flush sweep's
    work list. Channels fully caught up, or still active, are excluded so the sweep does no work for
    them. ``idle_before`` is an ISO timestamp (now − idle_flush_hours)."""
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        rows = conn.execute(
            """
            SELECT c.channel_id
            FROM memory_ingest_cursors c
            JOIN messages m ON m.channel_id = c.channel_id
            GROUP BY c.channel_id
            HAVING MAX(m.created_at) < ? AND MAX(m.created_at) > c.last_ingested_at
            """,
            (str(idle_before),),
        ).fetchall()
    return [int(r[0]) for r in rows]


__all__ = ["advance_cursor", "get_cursor", "list_idle_pending_channels"]
