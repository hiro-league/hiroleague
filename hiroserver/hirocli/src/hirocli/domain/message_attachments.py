"""Message attachment persistence for history-reloadable media."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from hiro_commons.timestamps import utc_iso, utc_now

from .data_store import data_db_path, data_dir, ensure_data_db


def attachment_ref(message_external_id: str, slot_index: int) -> str:
    """Return the deterministic logical ref for one message attachment slot."""
    return f"message_attachment:{message_external_id}:{slot_index}"


def media_file_path(workspace_path: Path, media_path: str) -> Path:
    """Resolve a data-relative attachment media path to an absolute path."""
    return data_dir(workspace_path) / media_path


def insert_attachment(
    workspace_path: Path,
    *,
    message_pk: int,
    slot_index: int,
    content_type: str,
    blob_id: str,
    media_type: str,
    size: int,
    media_path: str,
    filename: str | None = None,
    duration_ms: int | None = None,
    metadata: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> int:
    """Insert a tracked attachment row and return its integer PK."""
    ensure_data_db(workspace_path)
    ts = created_at or utc_iso(utc_now())
    meta_json = json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":"))
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        cursor = conn.execute(
            """
            INSERT INTO message_attachments
                (message_pk, slot_index, content_type, blob_id, media_type, size,
                 media_path, filename, duration_ms, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_pk,
                slot_index,
                content_type,
                blob_id,
                media_type,
                size,
                media_path,
                filename,
                duration_ms,
                meta_json,
                ts,
            ),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]


def list_attachments_for_message(
    workspace_path: Path,
    message_pk: int,
) -> list[dict[str, Any]]:
    """Return attachments for one message, ordered by slot."""
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM message_attachments
            WHERE message_pk = ?
            ORDER BY slot_index ASC
            """,
            (message_pk,),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_attachment(
    workspace_path: Path,
    *,
    message_pk: int,
    slot_index: int,
) -> dict[str, Any] | None:
    """Return one attachment by owning message PK and slot."""
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT * FROM message_attachments
            WHERE message_pk = ? AND slot_index = ?
            """,
            (message_pk, slot_index),
        ).fetchone()
    return _row_to_dict(row) if row is not None else None


def get_attachment_by_message_external_id(
    workspace_path: Path,
    *,
    message_external_id: str,
    slot_index: int,
) -> dict[str, Any] | None:
    """Return one attachment by public message id and slot."""
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT a.*
            FROM message_attachments a
            JOIN messages m ON m.id = a.message_pk
            WHERE m.external_id = ? AND a.slot_index = ?
            """,
            (message_external_id, slot_index),
        ).fetchone()
    return _row_to_dict(row) if row is not None else None


def find_by_blob_id(workspace_path: Path, blob_id: str) -> dict[str, Any] | None:
    """Return the tracked attachment for a blob id.

    Each attachment row owns its own bytes (no cross-row blob sharing — see
    `docs/channel-messages-clear-design.md`), so this lookup returns at most
    one row. ``LIMIT 1`` + ``ORDER BY id`` is retained as a defensive guard:
    if a future bug somehow inserts two rows with the same digest, callers
    still see the older one deterministically.

    Joins ``messages`` so callers (logging in particular) can refer to the
    public ``message_external_id`` without a second round-trip.
    """
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT a.*, m.external_id AS message_external_id
            FROM message_attachments a
            JOIN messages m ON m.id = a.message_pk
            WHERE a.blob_id = ?
            ORDER BY a.id ASC
            LIMIT 1
            """,
            (blob_id,),
        ).fetchone()
    return _row_to_dict(row) if row is not None else None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    if d.get("metadata"):
        try:
            d["metadata"] = json.loads(d["metadata"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d
