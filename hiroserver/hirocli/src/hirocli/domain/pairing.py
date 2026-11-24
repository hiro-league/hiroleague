"""Pairing session and approved-device persistence helpers.

All functions are workspace-scoped — they accept workspace_path: Path.

Pairing sessions are short-lived and read at boot; they stay as a JSON file
under the ephemeral runtime dir:
  <workspace>/run/pairing_session.json

Approved devices are durable structured records; they are stored in the
devices table of workspace.db.
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from hiro_commons.constants.domain import DEFAULT_PAIRING_CODE_LENGTH, DEFAULT_PAIRING_CODE_TTL_SECONDS
from hiro_commons.constants.storage import PAIRING_SESSION_FILENAME
from hiro_commons.timestamps import utc_iso

from .config import workspace_run_dir
from .db import db_path, ensure_db
from .events import DomainEvent, DomainEventType, get_domain_event_bus

logger = logging.getLogger(__name__)


class PairingSession(BaseModel):
    code: str
    created_at: datetime
    ttl_seconds: int
    # Permissions phase 3: the person the device approved with this code belongs to ("" = the owner)
    person_id: str = ""

    @property
    def expires_at(self) -> datetime:
        return self.created_at + timedelta(seconds=self.ttl_seconds)

    def is_valid(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        return current < self.expires_at

    def remaining_seconds(self, now: datetime | None = None) -> int:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        delta = self.expires_at - current
        return max(0, int(delta.total_seconds()))


class ApprovedDevice(BaseModel):
    device_id: str
    device_public_key: str
    paired_at: datetime
    expires_at: datetime | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    device_name: str | None = None
    # Permissions phase 3: the person it belongs to; it shows and writes only that person's conversations
    person_id: str = ""


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _pairing_session_file(workspace_path: Path) -> Path:
    # Lives under <workspace>/run/ with the other ephemeral runtime state.
    return workspace_run_dir(workspace_path) / PAIRING_SESSION_FILENAME


# ---------------------------------------------------------------------------
# Pairing code
# ---------------------------------------------------------------------------

def generate_pairing_code(length: int = DEFAULT_PAIRING_CODE_LENGTH) -> str:
    if length <= 0:
        raise ValueError("pairing code length must be > 0")
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def create_pairing_session(
    code_length: int = DEFAULT_PAIRING_CODE_LENGTH,
    ttl_seconds: int = DEFAULT_PAIRING_CODE_TTL_SECONDS,
    person_id: str = "",
) -> PairingSession:
    if ttl_seconds <= 0:
        raise ValueError("pairing code ttl_seconds must be > 0")
    return PairingSession(
        code=generate_pairing_code(code_length),
        created_at=datetime.now(UTC),
        ttl_seconds=ttl_seconds,
        person_id=person_id,
    )


# ---------------------------------------------------------------------------
# Pairing session I/O — file-backed (short-lived, read at boot)
# ---------------------------------------------------------------------------

def load_pairing_session(workspace_path: Path) -> PairingSession | None:
    path = _pairing_session_file(workspace_path)
    if not path.exists():
        return None
    try:
        session = PairingSession.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read the pairing session file %s — treated as no session: %s", path, exc, exc_info=True)
        return None
    if not session.is_valid():
        clear_pairing_session(workspace_path)
        return None
    return session


def save_pairing_session(workspace_path: Path, session: PairingSession) -> None:
    workspace_run_dir(workspace_path).mkdir(parents=True, exist_ok=True)
    _pairing_session_file(workspace_path).write_text(
        session.model_dump_json(indent=2), encoding="utf-8"
    )


def clear_pairing_session(workspace_path: Path) -> None:
    try:
        _pairing_session_file(workspace_path).unlink()
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Approved devices I/O — backed by workspace.db devices table
# ---------------------------------------------------------------------------

def load_approved_devices(workspace_path: Path) -> list[ApprovedDevice]:
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM devices").fetchall()
        devices: list[ApprovedDevice] = []
        for row in rows:
            try:
                devices.append(
                    ApprovedDevice(
                        device_id=row["device_id"],
                        device_public_key=row["device_public_key"],
                        paired_at=datetime.fromisoformat(row["paired_at"]),
                        expires_at=(
                            datetime.fromisoformat(row["expires_at"])
                            if row["expires_at"]
                            else None
                        ),
                        metadata=json.loads(row["metadata"] or "{}"),
                        device_name=row["device_name"] or None,
                        person_id=row["person_id"] or "",
                    )
                )
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                logger.warning(
                    "Skipping corrupt device row (device_id=%r): %s",
                    row["device_id"] if row["device_id"] else "?",
                    exc,
                )
        return devices


def save_approved_devices(workspace_path: Path, devices: list[ApprovedDevice]) -> None:
    """Replace the full device list in workspace.db."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute("DELETE FROM devices")
        for device in devices:
            conn.execute(
                """
                INSERT INTO devices (device_id, device_public_key, paired_at, expires_at, metadata, device_name, person_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device.device_id,
                    device.device_public_key,
                    utc_iso(device.paired_at),
                    utc_iso(device.expires_at) if device.expires_at else None,
                    json.dumps(device.metadata),
                    device.device_name,
                    device.person_id,
                ),
            )
        conn.commit()
    _devices_changed(workspace_path)


def upsert_approved_device(workspace_path: Path, device: ApprovedDevice) -> None:
    """Insert or update a single approved device row."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute(
            """
            INSERT INTO devices (device_id, device_public_key, paired_at, expires_at, metadata, device_name, person_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                device_public_key = excluded.device_public_key,
                paired_at         = excluded.paired_at,
                expires_at        = excluded.expires_at,
                metadata          = excluded.metadata,
                device_name       = excluded.device_name,
                person_id         = excluded.person_id
            """,
            (
                device.device_id,
                device.device_public_key,
                utc_iso(device.paired_at),
                utc_iso(device.expires_at) if device.expires_at else None,
                json.dumps(device.metadata),
                device.device_name,
                device.person_id,
            ),
        )
        conn.commit()
    _devices_changed(workspace_path)


def revoke_approved_device(workspace_path: Path, device_id: str) -> bool:
    """Delete a device row by device_id. Returns True if a row was removed."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        cursor = conn.execute(
            "DELETE FROM devices WHERE device_id = ?", (device_id,)
        )
        conn.commit()
        removed = cursor.rowcount > 0
    if removed:
        _devices_changed(workspace_path)
    return removed


def paired_device_ids(workspace_path: Path) -> set[str]:
    """The devices that may connect: paired and not past their pass's expiry."""
    now = datetime.now(UTC)
    return {
        d.device_id for d in load_approved_devices(workspace_path)
        if d.expires_at is None or d.expires_at > now
    }


def _devices_changed(workspace_path: Path) -> None:
    get_domain_event_bus().publish(
        DomainEvent(type=DomainEventType.DEVICES_CHANGED, workspace_path=workspace_path, payload={})
    )


def get_device_name(workspace_path: Path, device_id: str) -> str | None:
    """Return the device_name for a given device_id, or None if not found or unset."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT device_name FROM devices WHERE device_id = ?", (device_id,)
        ).fetchone()
        return row["device_name"] if row and row["device_name"] else None


def device_person_id(workspace_path: Path, device_id: str) -> str:
    """The person a paired device belongs to (Permissions phase 3), "" for a device that isn't paired."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        row = conn.execute("SELECT person_id FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        return str(row[0] or "") if row else ""


def device_ids_of(workspace_path: Path, person_id: str) -> set[str]:
    """The devices that belong to a person."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        rows = conn.execute("SELECT device_id FROM devices WHERE person_id = ?", (person_id,)).fetchall()
        return {str(r[0]) for r in rows}


def set_device_person(workspace_path: Path, device_id: str, person_id: str) -> bool:
    """Say whose a paired device is (the admin's Devices page). Returns False when no such device is paired."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        changed = conn.execute(
            "UPDATE devices SET person_id = ? WHERE device_id = ?", (person_id, device_id)
        ).rowcount
        conn.commit()
    if changed:
        _devices_changed(workspace_path)
    return changed > 0
