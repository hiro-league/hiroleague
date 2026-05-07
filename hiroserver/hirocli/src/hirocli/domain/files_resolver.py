"""Resolve ``ref`` strings and blob ids to on-disk files for file communication."""

from __future__ import annotations

from pathlib import Path

from .blob_store import blob_id_for_file
from .character import list_character_dirs, resolve_character_photo_file_for_http


def resolve_ref(workspace_path: Path, ref: str) -> tuple[Path, str, str]:
    """Return ``(path, media_type, blob_id)`` for a logical reference.

    Reference shape: ``<kind>:<id>`` (see docs/file-communication-implementation.md §4).
    """
    ref = ref.strip()
    if ":" not in ref:
        raise ValueError("invalid ref: expected '<kind>:<id>'")
    kind, rest = ref.split(":", 1)
    kind = kind.strip().lower()
    rid = rest.strip()
    if kind == "character_photo":
        if not rid:
            raise ValueError("character_photo ref requires id")
        path, media_type = resolve_character_photo_file_for_http(workspace_path, rid)
        bid = blob_id_for_file(path)
        return path.resolve(), media_type, bid
    raise FileNotFoundError(f"unknown ref kind: {kind}")


def resolve_blob_id(workspace_path: Path, blob_id: str) -> tuple[Path, str]:
    """Map a ``sha256:…`` id previously issued by this workspace to a readable file.

    Phase 1 only indexes character photo files (same bytes as ``characters.list``).
    """
    blob_id = blob_id.strip()
    if not blob_id.startswith("sha256:"):
        raise ValueError("blob_id must start with sha256:")
    want = blob_id[7:].strip().lower()
    if len(want) != 64:
        raise ValueError("blob_id has invalid sha256 length")

    from .blob_store import sha256_hex_of_file

    seen_resolved: set[str] = set()
    for cid in list_character_dirs(workspace_path):
        try:
            path, media_type = resolve_character_photo_file_for_http(workspace_path, cid)
        except FileNotFoundError:
            continue
        key = str(path.resolve())
        if key in seen_resolved:
            continue
        seen_resolved.add(key)
        if sha256_hex_of_file(path).lower() == want:
            return path.resolve(), media_type
    raise FileNotFoundError(f"no file matches blob_id {blob_id}")
