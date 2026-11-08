"""Paired extensions and their pairing code.

An extension is a program that runs on its own (HomeHiro first) and signs in on
the workspace's extension socket (see runtime/extension_manager.py). Pairing is
like the app's: the admin creates a short-lived code; the extension sends it with
its own public key; the core keeps the public key here and checks a signed
challenge on every later connection.

- The pairing code is short-lived and lives under the ephemeral run dir:
  <workspace>/run/extension_pairing_session.json (separate from the devices'
  code, so a code shown for the app can't pair an extension and vice versa).
- Paired extensions are durable rows in the ``extensions`` table of workspace.db.

All functions are workspace-scoped and synchronous (CLI and admin threads); the
runtime calls them from a worker thread.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from hiro_commons.timestamps import utc_iso

from .config import workspace_run_dir
from .db import db_path, ensure_db
from .pairing import PairingSession, create_pairing_session

logger = logging.getLogger(__name__)

_PAIRING_SESSION_FILENAME = "extension_pairing_session.json"


class PairedExtension(BaseModel):
    extension_id: str
    name: str = ""
    public_key: str
    paired_at: datetime
    last_seen: datetime | None = None
    # What the extension last said about itself (version, description, offers, uses).
    info: dict[str, Any] = Field(default_factory=dict)
    # Phase 7a: the use ids it declared before its uses last changed (the Uses page marks
    # a use "new" when it isn't in this list).
    uses_before: list[str] = Field(default_factory=list)

    def declared_uses(self) -> list[dict[str, Any]]:
        """The AI uses it last declared (ExtensionUse dicts: id, name, pictures, sound, json)."""
        return declared_uses(self.info)


def declared_uses(info: dict[str, Any]) -> list[dict[str, Any]]:
    """The ``uses`` list of an extension's info dict, keeping only well-formed entries."""
    raw = info.get("uses")
    if not isinstance(raw, list):
        return []
    return [u for u in raw if isinstance(u, dict) and isinstance(u.get("id"), str) and u["id"]]


def _use_ids(info: dict[str, Any]) -> list[str]:
    return [u["id"] for u in declared_uses(info)]


# ---------------------------------------------------------------------------
# Pairing code
# ---------------------------------------------------------------------------


def _pairing_session_file(workspace_path: Path) -> Path:
    return workspace_run_dir(workspace_path) / _PAIRING_SESSION_FILENAME


def start_extension_pairing(workspace_path: Path, *, code_length: int, ttl_seconds: int) -> PairingSession:
    """Create (and remember) a new pairing code; replaces any earlier one."""
    session = create_pairing_session(code_length=code_length, ttl_seconds=ttl_seconds)
    workspace_run_dir(workspace_path).mkdir(parents=True, exist_ok=True)
    _pairing_session_file(workspace_path).write_text(session.model_dump_json(indent=2), encoding="utf-8")
    return session


def load_extension_pairing(workspace_path: Path) -> PairingSession | None:
    """The current pairing code, or None when there is none or it expired."""
    path = _pairing_session_file(workspace_path)
    if not path.exists():
        return None
    try:
        session = PairingSession.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Extension pairing code file unreadable: %s", exc)
        return None
    if not session.is_valid():
        clear_extension_pairing(workspace_path)
        return None
    return session


def clear_extension_pairing(workspace_path: Path) -> None:
    try:
        _pairing_session_file(workspace_path).unlink()
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Paired extensions — workspace.db extensions table
# ---------------------------------------------------------------------------


def _row_to_extension(row: sqlite3.Row) -> PairedExtension:
    return PairedExtension(
        extension_id=row["extension_id"],
        name=row["name"] or "",
        public_key=row["public_key"],
        paired_at=datetime.fromisoformat(row["paired_at"]),
        last_seen=datetime.fromisoformat(row["last_seen"]) if row["last_seen"] else None,
        info=json.loads(row["info"] or "{}"),
        uses_before=json.loads(row["uses_before"] or "[]"),
    )


def list_paired_extensions(workspace_path: Path) -> list[PairedExtension]:
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM extensions ORDER BY paired_at").fetchall()
    extensions: list[PairedExtension] = []
    for row in rows:
        try:
            extensions.append(_row_to_extension(row))
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("Skipping corrupt extension row (extension_id=%r): %s", row["extension_id"], exc)
    return extensions


def get_paired_extension(workspace_path: Path, extension_id: str) -> PairedExtension | None:
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM extensions WHERE extension_id = ?", (extension_id,)).fetchone()
    if row is None:
        return None
    try:
        return _row_to_extension(row)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("Corrupt extension row (extension_id=%r): %s", extension_id, exc)
        return None


def add_paired_extension(workspace_path: Path, *, name: str, public_key: str, info: dict[str, Any]) -> PairedExtension:
    """Store a newly paired extension under a new id."""
    ensure_db(workspace_path)
    now = datetime.now(UTC)
    extension = PairedExtension(
        extension_id=uuid.uuid4().hex,
        name=name,
        public_key=public_key,
        paired_at=now,
        last_seen=now,
        info=info,
    )
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute(
            "INSERT INTO extensions (extension_id, name, public_key, paired_at, last_seen, info) VALUES (?, ?, ?, ?, ?, ?)",
            (
                extension.extension_id,
                extension.name,
                extension.public_key,
                utc_iso(extension.paired_at),
                utc_iso(now),
                json.dumps(extension.info),
            ),
        )
        conn.commit()
    return extension


def touch_paired_extension(workspace_path: Path, extension_id: str, *, info: dict[str, Any] | None = None) -> None:
    """Record that the extension was seen now (and what it said about itself)."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        if info is None:
            conn.execute(
                "UPDATE extensions SET last_seen = ? WHERE extension_id = ?",
                (utc_iso(datetime.now(UTC)), extension_id),
            )
        else:
            # Phase 7a: when the declared uses change, keep the previous ids so the Uses page
            # can mark the new ones; an unchanged list keeps the earlier "before" list.
            row = conn.execute("SELECT info FROM extensions WHERE extension_id = ?", (extension_id,)).fetchone()
            try:
                old_ids = _use_ids(json.loads(row[0] or "{}")) if row is not None else []
            except json.JSONDecodeError:
                old_ids = []
            new_ids = _use_ids(info)
            conn.execute(
                "UPDATE extensions SET last_seen = ?, info = ?, name = ? WHERE extension_id = ?",
                (utc_iso(datetime.now(UTC)), json.dumps(info), str(info.get("name") or ""), extension_id),
            )
            if sorted(old_ids) != sorted(new_ids):
                conn.execute(
                    "UPDATE extensions SET uses_before = ? WHERE extension_id = ?",
                    (json.dumps(old_ids), extension_id),
                )
        conn.commit()


def remove_paired_extension(workspace_path: Path, extension_id: str) -> bool:
    """Forget an extension's key. Returns True when a row was removed."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        cursor = conn.execute("DELETE FROM extensions WHERE extension_id = ?", (extension_id,))
        conn.commit()
        return cursor.rowcount > 0
