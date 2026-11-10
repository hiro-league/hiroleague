"""Character management tools — CRUD and photo upload.

CLI (commands/character.py), admin UI (Phase 3), agent, and POST /invoke call
these tools; domain logic lives in domain/character.py.

Phase 7b step 5: a character points at ordered AI profiles (``ai_profiles_json``) and voice profiles
(``voice_profiles_json``) instead of model lists, a tuning profile and TTS settings. Ids that don't
exist are refused; a profile whose model / voice can't be used right now (no key) is a warning.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain import character as character_domain
from ..domain.workspace import resolve_workspace, workspace_id_for_path
from .base import Tool, ToolParam


def _resolve_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


def _parse_json_string_list(label: str, raw: str | None) -> list[str] | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for {label}: {exc}") from exc
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise ValueError(f"{label} must be a JSON array of strings.")
    return data


def _check_profile_ids(workspace_path: Path, ai_profiles: list[str] | None, voice_profiles: list[str] | None) -> None:
    """Raise ValueError when the character would name an AI or voice profile that doesn't exist."""
    if ai_profiles is None and voice_profiles is None:
        return
    from ..domain.preferences import load_preferences, unknown_character_profiles

    missing = unknown_character_profiles(load_preferences(workspace_path), ai_profiles or [], voice_profiles or [])
    if missing:
        raise ValueError(" ".join(missing))


def character_profile_warnings(workspace_path: Path, ai_profiles: object | None, voice_profiles: object | None) -> list[str]:
    """Plain-words lines for the character's profiles that can't be used right now (non-blocking)."""
    wid = workspace_id_for_path(workspace_path)
    if wid is None:
        return []
    from ..domain.credential_store import CredentialStore
    from ..domain.preferences import load_preferences, profile_model_available, voice_profile_usable

    prefs = load_preferences(workspace_path)
    store = CredentialStore(workspace_path, wid)
    lines: list[str] = []
    for pid in _coerce_str_list(ai_profiles):
        profile = prefs.ai.profiles.get(pid)
        if profile is None:
            lines.append(f'AI profile "{pid}" doesn\'t exist any more.')
        elif profile.is_plan:
            lines.append(f'AI profile "{pid}" uses a plan tool ({profile.model}); chat skips it.')
        elif not profile_model_available(profile.model, store):
            lines.append(f'AI profile "{pid}": {profile.model} can\'t be used now (its provider isn\'t set up).')
    for pid in _coerce_str_list(voice_profiles):
        voice = prefs.voice.profiles.get(pid)
        if voice is None:
            lines.append(f'Voice profile "{pid}" doesn\'t exist any more.')
        elif not voice_profile_usable(voice, store):
            lines.append(f'Voice profile "{pid}": {voice.provider} has no API key, so it won\'t speak.')
    return lines


def _coerce_str_list(value: object | None) -> list[str]:
    """Normalize detail dict fields so corrupt on-disk JSON does not break validation."""
    if value is None:
        return []
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return list(value)
    return []


def _parse_json_list_or_clear(label: str, raw: str | None) -> list[str] | None:
    """Update semantics: None or "" = leave as is (the admin form sends "" for untouched); "[]" clears
    the list; else a JSON string array."""
    if raw is None or not str(raw).strip():
        return None
    return _parse_json_string_list(label, raw) or []


def _parse_json_object(label: str, raw: str | None) -> dict[str, Any] | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for {label}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return data


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class CharacterListResult:
    characters: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CharacterGetResult:
    character: dict[str, Any]


@dataclass
class CharacterCreateResult:
    character: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


@dataclass
class CharacterUpdateResult:
    character: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


@dataclass
class CharacterDeleteResult:
    deleted: bool
    character_id: str


@dataclass
class CharacterUploadPhotoResult:
    character_id: str
    photo_filename: str


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class CharacterListTool(Tool):
    name = "character_list"
    description = "List all characters in the workspace (id, name, profile fields, default flag)"
    params = {
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, workspace: str | None = None) -> CharacterListResult:
        workspace_path = _resolve_path(workspace)
        rows = character_domain.list_characters_detailed(workspace_path)
        return CharacterListResult(characters=rows)


class CharacterGetTool(Tool):
    name = "character_get"
    description = "Load full character configuration including prompt and backstory text"
    params = {
        "character_id": ToolParam(str, "Character id (slug, e.g. hiro)"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, character_id: str, workspace: str | None = None) -> CharacterGetResult:
        workspace_path = _resolve_path(workspace)
        detail = character_domain.get_character_detail(workspace_path, character_id)
        return CharacterGetResult(character=detail)


class CharacterCreateTool(Tool):
    agent_default = False
    name = "character_create"
    description = "Create a new character with its own folder under characters/<id>/"
    params = {
        "character_id": ToolParam(str, "New character id (3-32 char slug: a-z, 0-9, hyphens)"),
        "name": ToolParam(str, "Display name"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
        "description": ToolParam(str, "Short profile description", required=False),
        "prompt": ToolParam(
            str,
            "System prompt (persona). Omit to use the built-in default text.",
            required=False,
        ),
        "backstory": ToolParam(str, "Static backstory markdown", required=False),
        "ai_profiles_json": ToolParam(
            str,
            'JSON array of AI profile ids in order, e.g. ["hiro-chat"]; empty = Hiro\'s chat profile',
            required=False,
        ),
        "voice_profiles_json": ToolParam(
            str,
            "JSON array of voice profile ids in order; empty = Hiro's own voice",
            required=False,
        ),
        "emotions_enabled": ToolParam(bool, "Enable emotions flag (default false)", required=False),
        "extras_json": ToolParam(str, "JSON object for extra metadata", required=False),
    }

    def execute(
        self,
        character_id: str,
        name: str,
        workspace: str | None = None,
        description: str | None = None,
        prompt: str | None = None,
        backstory: str | None = None,
        ai_profiles_json: str | None = None,
        voice_profiles_json: str | None = None,
        emotions_enabled: bool | None = None,
        extras_json: str | None = None,
    ) -> CharacterCreateResult:
        workspace_path = _resolve_path(workspace)
        ai_profiles = _parse_json_string_list("ai_profiles_json", ai_profiles_json)
        voice_profiles = _parse_json_string_list("voice_profiles_json", voice_profiles_json)
        _check_profile_ids(workspace_path, ai_profiles, voice_profiles)
        extras = _parse_json_object("extras_json", extras_json)
        detail = character_domain.create_character(
            workspace_path,
            character_id,
            name,
            description=description or "",
            prompt=prompt,
            backstory=backstory or "",
            ai_profiles=ai_profiles,
            voice_profiles=voice_profiles,
            emotions_enabled=bool(emotions_enabled) if emotions_enabled is not None else False,
            extras=extras,
        )
        warn = character_profile_warnings(workspace_path, detail.get("ai_profiles"), detail.get("voice_profiles"))
        return CharacterCreateResult(character=detail, warnings=warn)


class CharacterUpdateTool(Tool):
    agent_default = False
    name = "character_update"
    description = "Update an existing character; only provided fields are changed"
    params = {
        "character_id": ToolParam(str, "Character id to update"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
        "name": ToolParam(str, "Display name", required=False),
        "description": ToolParam(str, "Short profile description", required=False),
        "prompt": ToolParam(str, "System prompt (persona) markdown body", required=False),
        "backstory": ToolParam(str, "Static backstory markdown", required=False),
        "ai_profiles_json": ToolParam(
            str, "JSON array of AI profile ids in order (replaces the list; [] = Hiro's chat profile)", required=False
        ),
        "voice_profiles_json": ToolParam(
            str, "JSON array of voice profile ids in order (replaces the list; [] = Hiro's own voice)", required=False
        ),
        "emotions_enabled": ToolParam(bool, "Emotions participation flag", required=False),
        "extras_json": ToolParam(str, "JSON object replacing extras when set", required=False),
    }

    def execute(
        self,
        character_id: str,
        workspace: str | None = None,
        name: str | None = None,
        description: str | None = None,
        prompt: str | None = None,
        backstory: str | None = None,
        ai_profiles_json: str | None = None,
        voice_profiles_json: str | None = None,
        emotions_enabled: bool | None = None,
        extras_json: str | None = None,
    ) -> CharacterUpdateResult:
        workspace_path = _resolve_path(workspace)
        ai_profiles = _parse_json_list_or_clear("ai_profiles_json", ai_profiles_json)
        voice_profiles = _parse_json_list_or_clear("voice_profiles_json", voice_profiles_json)
        _check_profile_ids(workspace_path, ai_profiles, voice_profiles)
        extras = _parse_json_object("extras_json", extras_json)
        detail = character_domain.update_character(
            workspace_path,
            character_id,
            name=name,
            description=description,
            prompt=prompt,
            backstory=backstory,
            ai_profiles=ai_profiles,
            voice_profiles=voice_profiles,
            emotions_enabled=emotions_enabled,
            extras=extras,
        )
        warn = character_profile_warnings(workspace_path, detail.get("ai_profiles"), detail.get("voice_profiles"))
        return CharacterUpdateResult(character=detail, warnings=warn)


class CharacterDeleteTool(Tool):
    agent_default = False
    name = "character_delete"
    description = "Delete a character folder and its workspace.db row (cannot delete the default)"
    params = {
        "character_id": ToolParam(str, "Character id to delete"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, character_id: str, workspace: str | None = None) -> CharacterDeleteResult:
        workspace_path = _resolve_path(workspace)
        deleted = character_domain.delete_character(workspace_path, character_id)
        return CharacterDeleteResult(deleted=deleted, character_id=character_id.strip())


class CharacterUploadPhotoTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "character_upload_photo"
    description = "Copy an image file into the character folder as photo.<ext> (replaces prior photo.*)"
    params = {
        "character_id": ToolParam(str, "Character id"),
        "photo_path": ToolParam(str, "Absolute path to an image file (.png, .jpg, .webp, .gif)"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(
        self,
        character_id: str,
        photo_path: str,
        workspace: str | None = None,
    ) -> CharacterUploadPhotoResult:
        workspace_path = _resolve_path(workspace)
        src = Path(photo_path).expanduser()
        name = character_domain.replace_character_photo(workspace_path, character_id, src)
        return CharacterUploadPhotoResult(character_id=character_id.strip(), photo_filename=name)
