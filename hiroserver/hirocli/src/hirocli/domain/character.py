"""Character entity — file-backed content plus workspace.db index.

Dual storage: ``characters`` table (see domain/db.py) holds id, name, is_default,
folder_path, timestamps. ``<workspace>/characters/<id>/`` holds character.json,
prompt.md, backstory.md, and an optional photo file.

Phase 1: seed and file I/O. Phase 2: domain CRUD used by tools/character.py.

When ``has_photo`` is false, HTTP/profile code (Phase 6) should serve a single
packaged default avatar from the app — not a per-character file under the workspace.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from hiro_commons.constants.storage import CHARACTERS_DIR, DEFAULT_CHARACTER_ID
from hiro_commons.timestamps import utc_iso, utc_now

from .db import db_path, ensure_db

logger = logging.getLogger(__name__)

CharacterChangeSubscriber = Callable[[Path, str], None]
_CHARACTER_CHANGE_SUBSCRIBERS: list[CharacterChangeSubscriber] = []


def subscribe_character_changes(callback: CharacterChangeSubscriber) -> None:
    if callback not in _CHARACTER_CHANGE_SUBSCRIBERS:
        _CHARACTER_CHANGE_SUBSCRIBERS.append(callback)


def unsubscribe_character_changes(callback: CharacterChangeSubscriber) -> None:
    if callback in _CHARACTER_CHANGE_SUBSCRIBERS:
        _CHARACTER_CHANGE_SUBSCRIBERS.remove(callback)


def _notify_character_changed(workspace_path: Path, character_id: str) -> None:
    for callback in list(_CHARACTER_CHANGE_SUBSCRIBERS):
        try:
            callback(workspace_path, character_id)
        except Exception:
            logger.exception("character change subscriber failed", extra={"character_id": character_id})

# Packaged defaults live next to the internal package (see characters/hiro/).
_HIROCLI_ROOT = Path(__file__).resolve().parent.parent
_PACKAGED_HIRO_DIR = _HIROCLI_ROOT / "characters" / DEFAULT_CHARACTER_ID

CHARACTER_JSON_NAME = "character.json"
PROMPT_MD_NAME = "prompt.md"
BACKSTORY_MD_NAME = "backstory.md"

# Default system prompt text for new workspaces (seeded into default character prompt.md).
DEFAULT_PROMPT_TEXT = """\
You are a helpful home assistant running on Hiro.
Answer questions concisely and helpfully.
"""

DEFAULT_BACKSTORY_TEXT = ""


class Character(BaseModel):
    """In-memory character: JSON metadata plus markdown and photo discovery."""

    id: str
    name: str
    description: str = ""
    llm_models: list[str] = Field(default_factory=list)
    voice_models: list[str] = Field(default_factory=list)
    # Optional TTS tuning: one preset per provider id (catalog), one global instruction string.
    tts_instructions: str = ""
    tts_voice_by_provider: dict[str, str] = Field(default_factory=dict)
    emotions_enabled: bool = False
    extras: dict[str, Any] = Field(default_factory=dict)
    prompt: str = ""
    backstory: str = ""
    has_photo: bool = False
    photo_filename: str | None = None

    def json_payload(self) -> dict[str, Any]:
        """Serialize fields stored in character.json (not prompt/backstory/photo)."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "llm_models": self.llm_models,
            "voice_models": self.voice_models,
            "tts_instructions": self.tts_instructions,
            "tts_voice_by_provider": dict(self.tts_voice_by_provider),
            "emotions_enabled": self.emotions_enabled,
            "extras": self.extras,
        }


def characters_root(workspace_path: Path) -> Path:
    return workspace_path / CHARACTERS_DIR


def character_dir(workspace_path: Path, character_id: str) -> Path:
    return characters_root(workspace_path) / character_id


def _detect_photo(char_dir: Path) -> tuple[bool, str | None]:
    for name in ("photo.png", "photo.jpg", "photo.jpeg", "photo.webp", "photo.gif"):
        p = char_dir / name
        if p.is_file():
            return True, name
    for p in sorted(char_dir.glob("photo.*")):
        if p.is_file():
            return True, p.name
    return False, None


def load_character_from_disk(workspace_path: Path, character_id: str) -> Character:
    """Load character.json, prompt.md, backstory.md, and photo metadata from disk."""
    cdir = character_dir(workspace_path, character_id)
    json_path = cdir / CHARACTER_JSON_NAME
    if not json_path.is_file():
        raise FileNotFoundError(f"Missing {json_path}")

    raw = json.loads(json_path.read_text(encoding="utf-8"))
    has_photo, photo_name = _detect_photo(cdir)
    prompt_path = cdir / PROMPT_MD_NAME
    back_path = cdir / BACKSTORY_MD_NAME
    prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.is_file() else ""
    backstory = back_path.read_text(encoding="utf-8") if back_path.is_file() else ""

    tts_map: dict[str, str] = {}
    raw_voices = raw.get("tts_voice_by_provider")
    if isinstance(raw_voices, dict):
        for k, v in raw_voices.items():
            if isinstance(k, str) and isinstance(v, str):
                tts_map[k] = v

    return Character(
        id=str(raw.get("id", character_id)),
        name=str(raw.get("name", character_id)),
        description=str(raw.get("description", "")),
        llm_models=list(raw.get("llm_models") or []),
        voice_models=list(raw.get("voice_models") or []),
        tts_instructions=str(raw.get("tts_instructions") or ""),
        tts_voice_by_provider=tts_map,
        emotions_enabled=bool(raw.get("emotions_enabled", False)),
        extras=dict(raw.get("extras") or {}),
        prompt=prompt,
        backstory=backstory,
        has_photo=has_photo,
        photo_filename=photo_name,
    )


def save_character_to_disk(workspace_path: Path, character: Character) -> None:
    """Write character.json, prompt.md, and backstory.md. Does not remove or replace photo."""
    cdir = character_dir(workspace_path, character.id)
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / CHARACTER_JSON_NAME).write_text(
        json.dumps(character.json_payload(), indent=2) + "\n",
        encoding="utf-8",
    )
    (cdir / PROMPT_MD_NAME).write_text(character.prompt, encoding="utf-8")
    (cdir / BACKSTORY_MD_NAME).write_text(character.backstory, encoding="utf-8")


def list_character_dirs(workspace_path: Path) -> list[str]:
    """Return character ids that have a character.json under ``characters/<id>/``."""
    root = characters_root(workspace_path)
    if not root.is_dir():
        return []
    ids: list[str] = []
    for sub in sorted(root.iterdir()):
        if sub.is_dir() and (sub / CHARACTER_JSON_NAME).is_file():
            ids.append(sub.name)
    return ids


def _folder_has_character_json(char_dir: Path) -> bool:
    return (char_dir / CHARACTER_JSON_NAME).is_file()


def _copy_packaged_hiro_if_needed(workspace_path: Path) -> Path:
    """Ensure ``characters/hiro`` exists with packaged files; return that directory."""
    dest = character_dir(workspace_path, DEFAULT_CHARACTER_ID)
    if not _PACKAGED_HIRO_DIR.is_dir():
        logger.warning(
            "Packaged default character directory missing — using inline defaults",
            expected=str(_PACKAGED_HIRO_DIR),
        )
        dest.mkdir(parents=True, exist_ok=True)
        if not _folder_has_character_json(dest):
            _write_inline_default_hiro_files(dest)
        return dest

    if not dest.exists():
        shutil.copytree(_PACKAGED_HIRO_DIR, dest)
        return dest

    if not _folder_has_character_json(dest):
        for name in (
            CHARACTER_JSON_NAME,
            PROMPT_MD_NAME,
            BACKSTORY_MD_NAME,
            "photo.png",
        ):
            src = _PACKAGED_HIRO_DIR / name
            if src.is_file() and not (dest / name).exists():
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest / name)
    return dest


def _write_inline_default_hiro_files(dest: Path) -> None:
    """Fallback when package data directory is absent (e.g. broken install)."""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / CHARACTER_JSON_NAME).write_text(
        json.dumps(
            {
                "id": DEFAULT_CHARACTER_ID,
                "name": "Hiro",
                "description": "Your personal AI assistant running on Hiro League.",
                "llm_models": [],
                "voice_models": [],
                "tts_instructions": "",
                "tts_voice_by_provider": {},
                "emotions_enabled": False,
                "extras": {},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (dest / PROMPT_MD_NAME).write_text(DEFAULT_PROMPT_TEXT, encoding="utf-8")
    (dest / BACKSTORY_MD_NAME).write_text(DEFAULT_BACKSTORY_TEXT, encoding="utf-8")


def _ensure_hiro_db_row(conn: sqlite3.Connection, workspace_path: Path) -> None:
    """Insert or refresh the ``hiro`` index row from disk metadata."""
    ch = load_character_from_disk(workspace_path, DEFAULT_CHARACTER_ID)
    now = utc_iso(utc_now())
    folder_rel = f"{CHARACTERS_DIR}/{DEFAULT_CHARACTER_ID}"

    row = conn.execute(
        "SELECT id FROM characters WHERE id = ?",
        (DEFAULT_CHARACTER_ID,),
    ).fetchone()

    if row is None:
        total = conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0]
        is_default = 1 if total == 0 else 0
        conn.execute(
            """
            INSERT INTO characters (id, name, is_default, folder_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ch.id, ch.name, is_default, folder_rel, now, now),
        )
        logger.info("Seeded default character row in workspace.db", character_id=ch.id)
    else:
        conn.execute(
            """
            UPDATE characters SET name = ?, folder_path = ?, updated_at = ?
            WHERE id = ?
            """,
            (ch.name, folder_rel, now, DEFAULT_CHARACTER_ID),
        )


def seed_default_characters(workspace_path: Path) -> None:
    """Copy packaged ``hiro`` if missing and ensure workspace.db index row exists (idempotent)."""
    ensure_db(workspace_path)
    _copy_packaged_hiro_if_needed(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        _ensure_hiro_db_row(conn, workspace_path)
        conn.commit()


def default_character_id(workspace_path: Path) -> str:
    """Return the id of the default character (``is_default = 1``), usually ``hiro``."""
    seed_default_characters(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        row = conn.execute(
            "SELECT id FROM characters WHERE is_default = 1 LIMIT 1"
        ).fetchone()
        if row and row[0]:
            return str(row[0])
    return DEFAULT_CHARACTER_ID


def load_default_character_prompt(workspace_path: Path) -> str:
    """Return prompt.md for the default character, with empty file falling back to DEFAULT_PROMPT_TEXT."""
    seed_default_characters(workspace_path)
    cid = default_character_id(workspace_path)
    ch = load_character_from_disk(workspace_path, cid)
    text = (ch.prompt or "").strip()
    return text if text else DEFAULT_PROMPT_TEXT.strip()


def save_default_character_prompt(workspace_path: Path, prompt: str) -> None:
    """Write prompt.md for the default character."""
    seed_default_characters(workspace_path)
    cid = default_character_id(workspace_path)
    ch = load_character_from_disk(workspace_path, cid)
    ch.prompt = prompt.strip()
    save_character_to_disk(workspace_path, ch)
    now = utc_iso(utc_now())
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute(
            "UPDATE characters SET updated_at = ? WHERE id = ?",
            (now, cid),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Phase 2 — CRUD + photo (shared by tools/character.py)
# ---------------------------------------------------------------------------

_CHARACTER_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def normalize_character_id(character_id: str) -> str:
    """Validate and return a normalized slug (lowercase). Raises ValueError if invalid."""
    s = character_id.strip().lower()
    if len(s) < 3 or len(s) > 32:
        raise ValueError("Character id must be 3-32 characters.")
    if not _CHARACTER_ID_RE.fullmatch(s):
        raise ValueError(
            "Character id must be slug-safe: lowercase letters, digits, and non-leading hyphens."
        )
    return s


def character_index_row_exists(workspace_path: Path, character_id: str) -> bool:
    """Return True if *character_id* exists in the workspace.db index."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        row = conn.execute(
            "SELECT 1 FROM characters WHERE id = ?", (character_id,)
        ).fetchone()
        return row is not None


def get_character_detail(workspace_path: Path, character_id: str) -> dict[str, Any]:
    """Merge DB index row with on-disk content for tools and APIs."""
    seed_default_characters(workspace_path)
    cid = character_id.strip()
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, name, is_default, folder_path, created_at, updated_at
            FROM characters WHERE id = ?
            """,
            (cid,),
        ).fetchone()
    if row is None:
        raise FileNotFoundError(f"Unknown character id: {cid}")
    ch = load_character_from_disk(workspace_path, cid)
    return {
        "id": ch.id,
        "name": ch.name,
        "description": ch.description,
        "is_default": bool(row["is_default"]),
        "folder_path": row["folder_path"],
        "prompt": ch.prompt,
        "backstory": ch.backstory,
        "llm_models": ch.llm_models,
        "voice_models": ch.voice_models,
        "tts_instructions": ch.tts_instructions,
        "tts_voice_by_provider": dict(ch.tts_voice_by_provider),
        "emotions_enabled": ch.emotions_enabled,
        "extras": ch.extras,
        "has_photo": ch.has_photo,
        "photo_filename": ch.photo_filename,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_characters_detailed(workspace_path: Path) -> list[dict[str, Any]]:
    """List all indexed characters with merged disk fields."""
    seed_default_characters(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, name, is_default, folder_path, created_at, updated_at
            FROM characters ORDER BY id
            """
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        rid = row["id"]
        try:
            ch = load_character_from_disk(workspace_path, rid)
            out.append(
                {
                    "id": rid,
                    "name": ch.name,
                    "description": ch.description,
                    "is_default": bool(row["is_default"]),
                    "folder_path": row["folder_path"],
                    "has_photo": ch.has_photo,
                    "photo_filename": ch.photo_filename,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        except FileNotFoundError:
            out.append(
                {
                    "id": rid,
                    "name": row["name"],
                    "description": "",
                    "is_default": bool(row["is_default"]),
                    "folder_path": row["folder_path"],
                    "has_photo": False,
                    "photo_filename": None,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "error": "character files missing on disk",
                }
            )
    return out


def create_character(
    workspace_path: Path,
    character_id: str,
    name: str,
    *,
    description: str = "",
    prompt: str | None = None,
    backstory: str = "",
    llm_models: list[str] | None = None,
    voice_models: list[str] | None = None,
    tts_instructions: str = "",
    tts_voice_by_provider: dict[str, str] | None = None,
    emotions_enabled: bool = False,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create ``characters/<id>/``, write files, and insert the DB index row."""
    seed_default_characters(workspace_path)
    cid = normalize_character_id(character_id)
    if character_index_row_exists(workspace_path, cid) or character_dir(workspace_path, cid).exists():
        raise ValueError(f"Character already exists: {cid}")
    prompt_text = DEFAULT_PROMPT_TEXT if prompt is None else prompt
    ch = Character(
        id=cid,
        name=name.strip() or cid,
        description=description,
        prompt=prompt_text,
        backstory=backstory,
        llm_models=list(llm_models or []),
        voice_models=list(voice_models or []),
        tts_instructions=tts_instructions.strip(),
        tts_voice_by_provider=dict(tts_voice_by_provider or {}),
        emotions_enabled=emotions_enabled,
        extras=dict(extras or {}),
    )
    save_character_to_disk(workspace_path, ch)
    now = utc_iso(utc_now())
    folder_rel = f"{CHARACTERS_DIR}/{cid}"
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute(
            """
            INSERT INTO characters (id, name, is_default, folder_path, created_at, updated_at)
            VALUES (?, ?, 0, ?, ?, ?)
            """,
            (ch.id, ch.name, folder_rel, now, now),
        )
        conn.commit()
    logger.info("Created character", character_id=cid, workspace=str(workspace_path))
    _notify_character_changed(workspace_path, cid)
    return get_character_detail(workspace_path, cid)


def update_character(
    workspace_path: Path,
    character_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    prompt: str | None = None,
    backstory: str | None = None,
    llm_models: list[str] | None = None,
    voice_models: list[str] | None = None,
    tts_instructions: str | None = None,
    tts_voice_by_provider: dict[str, str] | None = None,
    emotions_enabled: bool | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Patch on-disk character content and refresh ``name`` / ``updated_at`` in the index."""
    seed_default_characters(workspace_path)
    cid = character_id.strip()
    ch = load_character_from_disk(workspace_path, cid)
    if name is not None:
        ch.name = name.strip() or ch.name
    if description is not None:
        ch.description = description
    if prompt is not None:
        ch.prompt = prompt
    if backstory is not None:
        ch.backstory = backstory
    if llm_models is not None:
        ch.llm_models = list(llm_models)
    if voice_models is not None:
        ch.voice_models = list(voice_models)
    if tts_instructions is not None:
        ch.tts_instructions = tts_instructions.strip()
    if tts_voice_by_provider is not None:
        ch.tts_voice_by_provider = dict(tts_voice_by_provider)
    if emotions_enabled is not None:
        ch.emotions_enabled = emotions_enabled
    if extras is not None:
        ch.extras = dict(extras)
    save_character_to_disk(workspace_path, ch)
    now = utc_iso(utc_now())
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute(
            "UPDATE characters SET name = ?, updated_at = ? WHERE id = ?",
            (ch.name, now, cid),
        )
        conn.commit()
    logger.info("Updated character", character_id=cid, workspace=str(workspace_path))
    _notify_character_changed(workspace_path, cid)
    return get_character_detail(workspace_path, cid)


def delete_character(workspace_path: Path, character_id: str) -> bool:
    """Remove character folder and DB row. Raises ValueError if *character_id* is the default."""
    seed_default_characters(workspace_path)
    cid = character_id.strip()
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        row = conn.execute(
            "SELECT is_default FROM characters WHERE id = ?", (cid,)
        ).fetchone()
        if row is None:
            return False
        if int(row[0]) == 1:
            raise ValueError("Cannot delete the default character.")
    d = character_dir(workspace_path, cid)
    if d.is_dir():
        shutil.rmtree(d)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute("DELETE FROM characters WHERE id = ?", (cid,))
        conn.commit()
    logger.info("Deleted character", character_id=cid, workspace=str(workspace_path))
    _notify_character_changed(workspace_path, cid)
    return True


def character_photo_media_type(filename: str) -> str:
    """Content-Type for a character photo filename (workspace or packaged asset)."""
    lower = filename.lower()
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith(".gif"):
        return "image/gif"
    return "image/png"


def list_public_character_summaries(workspace_path: Path) -> list[dict[str, Any]]:
    """Minimal index rows for GET /characters (Phase 6 — Flutter profile list)."""
    rows = list_characters_detailed(workspace_path)
    wp = workspace_path
    result: list[dict[str, Any]] = []
    for r in rows:
        llm_models: list[str] = []
        voice_models: list[str] = []
        if not r.get("error"):
            try:
                ch = load_character_from_disk(wp, r["id"])
                llm_models = list(ch.llm_models)
                voice_models = list(ch.voice_models)
            except FileNotFoundError:
                pass
        result.append(
            {
                "id": r["id"],
                "name": r["name"],
                "description": r.get("description") or "",
                "has_photo": bool(r.get("has_photo")),
                "llm_models": llm_models,
                "voice_models": voice_models,
            }
        )
    return result


def public_character_profile(workspace_path: Path, character_id: str) -> dict[str, Any]:
    """Subset of character detail for GET /characters/{{id}}/profile."""
    d = get_character_detail(workspace_path, character_id)
    return {
        "id": d["id"],
        "name": d["name"],
        "description": d.get("description") or "",
        "has_photo": bool(d.get("has_photo")),
        "updated_at": d.get("updated_at") or "",
        # Same preference lists the agent uses (Phase 5); helps clients align with runtime.
        "llm_models": list(d.get("llm_models") or []),
        "voice_models": list(d.get("voice_models") or []),
    }


def packaged_default_character_photo_path() -> Path:
    """Packaged ``hiro`` photo used when a character has no uploaded photo."""
    return _PACKAGED_HIRO_DIR / "photo.png"


def resolve_character_photo_file_for_http(
    workspace_path: Path,
    character_id: str,
) -> tuple[Path, str]:
    """Absolute path and media type to serve for GET /characters/{{id}}/photo.

    Uses the character's ``photo.*`` when present; otherwise the packaged default
    avatar (same asset as seeded ``hiro``). Raises FileNotFoundError if the
    character is unknown or no image can be resolved.
    """
    seed_default_characters(workspace_path)
    cid = character_id.strip()
    if not character_index_row_exists(workspace_path, cid):
        raise FileNotFoundError(f"Unknown character id: {cid}")
    ch = load_character_from_disk(workspace_path, cid)
    if ch.has_photo and ch.photo_filename:
        path = (character_dir(workspace_path, cid) / ch.photo_filename).resolve()
        if path.is_file():
            return path, character_photo_media_type(ch.photo_filename)
    fallback = packaged_default_character_photo_path().resolve()
    if fallback.is_file():
        return fallback, "image/png"
    raise FileNotFoundError("No character photo and packaged default avatar is missing")


def effective_character_system_prompt(character: Character) -> str:
    """System prompt from ``prompt.md`` for LangGraph, with legacy empty-file fallback."""
    text = (character.prompt or "").strip()
    return text if text else DEFAULT_PROMPT_TEXT.strip()


def replace_character_photo(
    workspace_path: Path,
    character_id: str,
    source_file: Path,
) -> str:
    """Replace ``photo.*`` in the character folder; returns the new filename (e.g. ``photo.png``)."""
    seed_default_characters(workspace_path)
    cid = character_id.strip()
    src = source_file.resolve()
    if not src.is_file():
        raise FileNotFoundError(f"Photo file not found: {src}")
    cdir = character_dir(workspace_path, cid)
    if not (cdir / CHARACTER_JSON_NAME).is_file():
        raise FileNotFoundError(f"Unknown character id: {cid}")
    ext = src.suffix.lower() if src.suffix else ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        ext = ".png"
    # Read bytes before removing existing photo.* — source may be the same file.
    image_bytes = src.read_bytes()
    for p in list(cdir.glob("photo.*")):
        if p.is_file():
            p.unlink()
    dest_name = f"photo{ext}"
    (cdir / dest_name).write_bytes(image_bytes)
    now = utc_iso(utc_now())
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute(
            "UPDATE characters SET updated_at = ? WHERE id = ?",
            (now, cid),
        )
        conn.commit()
    logger.info("Updated character photo", character_id=cid, photo=dest_name)
    return dest_name
