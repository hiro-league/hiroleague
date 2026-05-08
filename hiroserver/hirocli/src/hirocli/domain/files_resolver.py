"""Resolve ``ref`` strings and blob ids to on-disk files for file communication."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from hiro_commons.log import Logger

from .blob_store import blob_id_for_file
from .character import list_character_dirs, resolve_character_photo_file_for_http
from .message_attachments import (
    get_attachment_by_message_external_id,
    find_by_blob_id,
    media_file_path,
)
from .pairing import load_approved_devices

log = Logger.get("FILES_RESOLVER")


def resolve_ref(
    workspace_path: Path,
    ref: str,
    *,
    requesting_device_id: str | None = None,
) -> tuple[Path, str, str]:
    """Return ``(path, media_type, blob_id)`` for a logical reference.

    Reference shape: ``<kind>:<id>`` (see docs/file-communication-implementation.md §4).
    """
    ref = ref.strip()
    if ":" not in ref:
        log.warning(
            "⚠️ Reference unresolved — unknown",
            reason="unknown_kind",
            ref=ref,
        )
        raise ValueError("invalid ref: expected '<kind>:<id>'")
    kind, rest = ref.split(":", 1)
    kind = kind.strip().lower()
    rid = rest.strip()
    if kind == "character_photo":
        if not rid:
            log.warning(
                "⚠️ Reference unresolved — character_photo:",
                reason="not_found",
            )
            raise ValueError("character_photo ref requires id")
        try:
            path, media_type = resolve_character_photo_file_for_http(
                workspace_path, rid
            )
        except FileNotFoundError:
            log.warning(
                f"⚠️ Reference unresolved — character_photo:{rid}",
                reason="not_found",
            )
            raise
        # Character photos are public workspace assets (avatars on
        # ``characters.list``), so no per-device authz is required — same
        # treatment as the resolve_blob_id character-scan fallback below.
        bid = blob_id_for_file(path)
        return path.resolve(), media_type, bid
    if kind == "message_attachment":
        if ":" not in rid:
            log.warning(
                f"⚠️ Reference unresolved — message_attachment:{rid}",
                reason="not_found",
            )
            raise ValueError(
                "message_attachment ref requires '<message_id>:<slot_index>'"
            )
        message_external_id, slot_raw = rid.rsplit(":", 1)
        message_external_id = message_external_id.strip()
        if not message_external_id:
            log.warning(
                f"⚠️ Reference unresolved — message_attachment:{rid}",
                reason="not_found",
            )
            raise ValueError("message_attachment ref requires message id")
        try:
            slot_index = int(slot_raw)
        except ValueError as exc:
            log.warning(
                f"⚠️ Reference unresolved — message_attachment:{rid}",
                reason="not_found",
            )
            raise ValueError("message_attachment slot_index must be an integer") from exc
        row = get_attachment_by_message_external_id(
            workspace_path,
            message_external_id=message_external_id,
            slot_index=slot_index,
        )
        if row is None:
            log.warning(
                f"⚠️ Reference unresolved — message_attachment:{rid}",
                reason="not_found",
            )
            raise FileNotFoundError(f"message attachment not found: {rid}")
        path = media_file_path(workspace_path, str(row["media_path"]))
        if not path.exists():
            log.warning(
                f"⚠️ Reference unresolved — message_attachment:{rid}",
                reason="not_found",
            )
            raise FileNotFoundError(f"message attachment file not found: {rid}")
        _authorize_requesting_device(
            workspace_path,
            requesting_device_id=requesting_device_id,
            ref_kind=kind,
            ref_id=rid,
        )
        return path.resolve(), str(row["media_type"]), str(row["blob_id"])
    log.warning(
        f"⚠️ Reference unresolved — {kind}:{rid}",
        reason="unknown_kind",
    )
    raise FileNotFoundError(f"unknown ref kind: {kind}")


def _authorize_requesting_device(
    workspace_path: Path,
    *,
    requesting_device_id: str | None,
    ref_kind: str,
    ref_id: str,
) -> None:
    if requesting_device_id is None or requesting_device_id == "server":
        return
    now = datetime.now(UTC)
    for device in load_approved_devices(workspace_path):
        if device.device_id != requesting_device_id:
            continue
        expires_at = device.expires_at
        if expires_at is None:
            return
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if now < expires_at:
            return
    log.warning(
        f"⚠️ Reference unresolved — {ref_kind}:{ref_id}",
        reason="unauthorized",
    )
    raise PermissionError(f"device is not authorized for ref: {ref_kind}:{ref_id}")


def resolve_blob_id(
    workspace_path: Path,
    blob_id: str,
    *,
    requesting_device_id: str | None = None,
) -> tuple[Path, str]:
    path, media_type, _kind, _detail = resolve_blob_id_with_kind(
        workspace_path,
        blob_id,
        requesting_device_id=requesting_device_id,
    )
    return path, media_type


def resolve_blob_id_with_kind(
    workspace_path: Path,
    blob_id: str,
    *,
    requesting_device_id: str | None = None,
) -> tuple[Path, str, str, dict[str, object]]:
    """Map a ``sha256:…`` id previously issued by this workspace to a readable file.

    Returns ``(path, media_type, kind, detail)`` where ``detail`` carries
    human-readable identity for logging/UX:

    - ``kind == "character_photo"`` → ``{"character_id": <cid>}``
    - ``kind == "message_attachment"`` → ``{"message_external_id", "slot_index",
      "duration_ms", "filename"}`` (any of these may be absent/None).

    Message attachments are indexed by ``blob_id``; character photos fall back to
    the legacy directory scan because they are not stored in the attachment table.
    """
    blob_id = blob_id.strip()
    if not blob_id.startswith("sha256:"):
        raise ValueError("blob_id must start with sha256:")
    want = blob_id[7:].strip().lower()
    if len(want) != 64:
        raise ValueError("blob_id has invalid sha256 length")

    attachment = find_by_blob_id(workspace_path, blob_id)
    if attachment is not None:
        path = media_file_path(workspace_path, str(attachment["media_path"]))
        if not path.exists():
            # Indexed row points to a missing file — surface the inconsistency
            # rather than masking it by falling back to the character scan.
            log.warning(
                f"⚠️ Reference unresolved — message_attachment:{attachment['id']}",
                reason="not_found",
                blob_id=blob_id,
            )
            raise FileNotFoundError(
                f"message attachment file missing on disk: {blob_id}"
            )
        _authorize_requesting_device(
            workspace_path,
            requesting_device_id=requesting_device_id,
            ref_kind="message_attachment",
            ref_id=str(attachment["id"]),
        )
        detail: dict[str, object] = {
            "message_external_id": attachment.get("message_external_id"),
            "slot_index": attachment.get("slot_index"),
            "duration_ms": attachment.get("duration_ms"),
            "filename": attachment.get("filename"),
        }
        return (
            path.resolve(),
            str(attachment["media_type"]),
            "message_attachment",
            detail,
        )

    from .blob_store import sha256_hex_of_file

    seen_resolved: set[str] = set()
    for cid in list_character_dirs(workspace_path):
        try:
            path, media_type = resolve_character_photo_file_for_http(
                workspace_path, cid
            )
        except FileNotFoundError:
            continue
        key = str(path.resolve())
        if key in seen_resolved:
            continue
        seen_resolved.add(key)
        if sha256_hex_of_file(path).lower() == want:
            # No authz on character photos — see ``resolve_ref`` rationale.
            return path.resolve(), media_type, "character_photo", {"character_id": cid}
    raise FileNotFoundError(f"no file matches blob_id {blob_id}")
