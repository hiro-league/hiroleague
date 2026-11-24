"""The extensions and the admin's pairing code.

An extension is any program that plugs into the core on its machine and signs in on
the workspace's one extension socket (see runtime/extension_manager.py): an app
(HomeHiro...), or a channel plugin the core starts (WhatsApp, devices, echo). Each
pairs once: it sends a code with its own public key; the core keeps the public key
here and checks a signed challenge on every later connection.

- The admin's pairing code (for an app) is short-lived and lives under the ephemeral run dir:
  <workspace>/run/extension_pairing_session.json (separate from the devices'
  code, so a code shown for the phone app can't pair an extension and vice versa).
  The code for a channel plugin is made by the manager when it starts it (in memory).
- Every extension is one row of ``extension_records`` in workspace.db. Its kind is set
  once, at pairing, from who made the code: KIND_APP (the admin's) or KIND_CHANNEL
  (the manager's), and with it whether it may relay chat and whether the core starts it.
  A channel plugin's own settings are channel_config.py's, on the same rows.

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

KIND_APP = "app"          # starts itself, pairs with the admin's code
KIND_CHANNEL = "channel"  # a channel plugin: the core starts it and makes its code; it relays other people's chat

TABLE = "extension_records"

# Names no extension may take: the core's own source, under which its admin grants are kept (core_features.CORE_SOURCE).
RESERVED_NAMES = frozenset({"hiroleague"})


class ExtensionNameTaken(ValueError):
    """An app's name is its key (rights, AI picks, asks are kept under it), so one name is one app. The message is for
    people."""

    def __init__(self, name: str, holder: PairedExtension | None) -> None:
        if holder is None:
            message = f"“{name}” is HiroLeague's own name; an app can't take it."
        else:
            message = (
                f"Another {'channel' if holder.kind == KIND_CHANNEL else 'app'} is already paired as “{name}”. "
                "Remove it in the core's admin (Extensions) first, then pair this one."
            )
        super().__init__(message)
        self.name = name
        self.holder = holder


def name_holder(workspace_path: Path, name: str, *, besides: str = "") -> PairedExtension | None:
    """The extension that holds ``name``, other than ``besides`` (an extension id), or None."""
    return next(
        (e for e in list_paired_extensions(workspace_path, kind=None) if e.name == name and e.extension_id != besides),
        None,
    )


def check_name_free(workspace_path: Path, name: str, *, besides: str = "") -> None:
    """Raise ExtensionNameTaken when ``name`` is reserved or another extension holds it (design.md §9: a second
    ``home`` would take HomeHiro's rights, picks and asks)."""
    if name in RESERVED_NAMES:
        raise ExtensionNameTaken(name, None)
    holder = name_holder(workspace_path, name, besides=besides)
    if holder is not None:
        raise ExtensionNameTaken(name, holder)


class PairedExtension(BaseModel):
    """One extension's row. A channel plugin not yet paired has no key (``public_key`` "") and no ``paired_at``."""

    extension_id: str
    name: str = ""
    kind: str = KIND_APP
    public_key: str = ""
    paired_at: datetime | None = None
    last_seen: datetime | None = None
    # Its kind's attributes: it may send frames for someone else (a phone, a WhatsApp contact), and the core starts it.
    relays_chat: bool = False
    started_by_core: bool = False
    # What the extension last said about itself (version, description, offers, uses).
    info: dict[str, Any] = Field(default_factory=dict)
    # Phase 7a: the use ids it declared before its uses last changed (the Uses page marks
    # a use "new" when it isn't in this list).
    uses_before: list[str] = Field(default_factory=list)

    def declared_uses(self) -> list[dict[str, Any]]:
        """The AI uses it last declared (ExtensionUse dicts: id, name, pictures, sound, json)."""
        return declared_uses(self.info)

    def declared_voice_uses(self) -> list[dict[str, Any]]:
        """The voice uses it last declared (Phase 7b, ExtensionVoiceUse dicts: id, name)."""
        return declared_uses(self.info, "voice_uses")

    def declared_search_uses(self, kind: str) -> list[dict[str, Any]]:
        """The embed (``kind="embedding"``) or rerank (``"rerank"``) uses it last declared (ExtensionSearchUse dicts)."""
        return declared_uses(self.info, "embed_uses" if kind == "embedding" else "rerank_uses")


def declared_uses(info: dict[str, Any], key: str = "uses") -> list[dict[str, Any]]:
    """The ``uses`` (or ``voice_uses``, ``embed_uses``, ``rerank_uses``) list of an extension's info dict, keeping only
    well-formed entries."""
    raw = info.get(key)
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
# The extensions — workspace.db extension_records table
# ---------------------------------------------------------------------------


def _row_to_extension(row: sqlite3.Row) -> PairedExtension:
    return PairedExtension(
        extension_id=row["extension_id"],
        name=row["name"] or "",
        kind=row["kind"] or KIND_APP,
        public_key=row["public_key"] or "",
        paired_at=datetime.fromisoformat(row["paired_at"]) if row["paired_at"] else None,
        last_seen=datetime.fromisoformat(row["last_seen"]) if row["last_seen"] else None,
        relays_chat=bool(row["relays_chat"]),
        started_by_core=bool(row["started_by_core"]),
        info=json.loads(row["info"] or "{}"),
        uses_before=json.loads(row["uses_before"] or "[]"),
    )


def list_paired_extensions(workspace_path: Path, *, kind: str | None = KIND_APP) -> list[PairedExtension]:
    """The extensions of one kind (the apps by default: uses, rights, sites and asks are theirs), or every one."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        if kind is None:
            rows = conn.execute(f"SELECT * FROM {TABLE} ORDER BY paired_at").fetchall()
        else:
            rows = conn.execute(f"SELECT * FROM {TABLE} WHERE kind = ? ORDER BY paired_at", (kind,)).fetchall()
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
        row = conn.execute(f"SELECT * FROM {TABLE} WHERE extension_id = ?", (extension_id,)).fetchone()
    if row is None:
        return None
    try:
        return _row_to_extension(row)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("Corrupt extension row (extension_id=%r): %s", extension_id, exc)
        return None


def add_paired_extension(workspace_path: Path, *, name: str, public_key: str, info: dict[str, Any]) -> PairedExtension:
    """Store a newly paired app under a new id (paired with the admin's code). Raises ExtensionNameTaken when the
    name is reserved or another extension holds it."""
    ensure_db(workspace_path)
    check_name_free(workspace_path, name)
    now = datetime.now(UTC)
    extension = PairedExtension(
        extension_id=uuid.uuid4().hex,
        name=name,
        kind=KIND_APP,
        public_key=public_key,
        paired_at=now,
        last_seen=now,
        info=info,
    )
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute(
            f"INSERT INTO {TABLE} (extension_id, name, kind, public_key, paired_at, last_seen, info, relays_chat, "
            "started_by_core) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)",
            (
                extension.extension_id,
                extension.name,
                KIND_APP,
                extension.public_key,
                utc_iso(now),
                utc_iso(now),
                json.dumps(extension.info),
            ),
        )
        conn.commit()
    return extension


def pair_started_extension(
    workspace_path: Path, *, name: str, public_key: str, info: dict[str, Any]
) -> PairedExtension | None:
    """Keep the key of a channel plugin the core started (paired with the manager's code), on its row, by name: a
    plugin that lost its key pairs again and keeps its id. None when no such row exists (removed meanwhile)."""
    ensure_db(workspace_path)
    now = utc_iso(datetime.now(UTC))
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        cursor = conn.execute(
            f"UPDATE {TABLE} SET public_key = ?, paired_at = ?, last_seen = ?, info = ? "
            "WHERE name = ? AND started_by_core = 1",
            (public_key, now, now, json.dumps(info), name),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
    return next((e for e in list_paired_extensions(workspace_path, kind=None)
                 if e.name == name and e.started_by_core), None)


def touch_paired_extension(workspace_path: Path, extension_id: str, *, info: dict[str, Any] | None = None) -> None:
    """Record that the extension was seen now (and what it said about itself)."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        if info is None:
            conn.execute(
                f"UPDATE {TABLE} SET last_seen = ? WHERE extension_id = ?",
                (utc_iso(datetime.now(UTC)), extension_id),
            )
        else:
            # Phase 7a: when the declared uses change, keep the previous ids so the Uses page
            # can mark the new ones; an unchanged list keeps the earlier "before" list.
            row = conn.execute(f"SELECT info FROM {TABLE} WHERE extension_id = ?", (extension_id,)).fetchone()
            try:
                old_ids = _use_ids(json.loads(row[0] or "{}")) if row is not None else []
            except json.JSONDecodeError:
                old_ids = []
            new_ids = _use_ids(info)
            conn.execute(
                f"UPDATE {TABLE} SET last_seen = ?, info = ?, name = ? WHERE extension_id = ?",
                (utc_iso(datetime.now(UTC)), json.dumps(info), str(info.get("name") or ""), extension_id),
            )
            if sorted(old_ids) != sorted(new_ids):
                conn.execute(
                    f"UPDATE {TABLE} SET uses_before = ? WHERE extension_id = ?",
                    (json.dumps(old_ids), extension_id),
                )
        conn.commit()


def remove_paired_extension(workspace_path: Path, extension_id: str) -> bool:
    """Forget an app: its row and its key. Returns True when a row was removed. (A channel plugin is removed with
    channel_config.delete_channel_config.)"""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        cursor = conn.execute(f"DELETE FROM {TABLE} WHERE extension_id = ? AND kind = ?", (extension_id, KIND_APP))
        conn.commit()
        return cursor.rowcount > 0
