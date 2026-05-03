"""Character management tools — CRUD and photo upload.

CLI (commands/character.py), admin UI (Phase 3), agent, and POST /invoke call
these tools; domain logic lives in domain/character.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain import character as character_domain
from ..domain.available_models import CharacterModelValidation, build_available_models_service
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


def character_model_validation_warnings(v: CharacterModelValidation) -> list[str]:
    """Human-readable lines for tool/CLI/admin consumers (non-blocking)."""
    lines: list[str] = []
    for mid in v.unknown_llm:
        lines.append(f'LLM model "{mid}" is not in the catalog.')
    for mid in v.unknown_voice:
        lines.append(f'Voice model "{mid}" is not in the catalog.')
    for d in v.deprecated_llm:
        hint = f' Consider "{d.replacement_id}".' if d.replacement_id else ""
        lines.append(
            f'LLM model "{d.model_id}" is deprecated (since {d.deprecated_since}).{hint}'
        )
    for d in v.deprecated_voice:
        hint = f' Consider "{d.replacement_id}".' if d.replacement_id else ""
        lines.append(
            f'Voice model "{d.model_id}" is deprecated (since {d.deprecated_since}).{hint}'
        )
    for mid in v.wrong_kind_llm:
        lines.append(
            f'LLM model "{mid}" is not a chat model (wrong model_kind for llm_models).'
        )
    for mid in v.wrong_kind_voice:
        lines.append(
            f'Voice model "{mid}" is not a TTS/STT model (wrong model_kind for voice_models).'
        )
    for mid in v.unavailable_llm:
        lines.append(
            f'LLM model "{mid}" is in the catalog but its provider is not configured for this workspace.'
        )
    for mid in v.unavailable_voice:
        lines.append(
            f'Voice model "{mid}" is in the catalog but its provider is not configured for this workspace.'
        )
    return lines


def _coerce_str_list(value: object | None) -> list[str]:
    """Normalize detail dict fields so corrupt on-disk JSON does not break validation."""
    if value is None:
        return []
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return list(value)
    return []


def _validate_character_model_warnings(
    workspace_path: Path,
    llm_models: object | None,
    voice_models: object | None,
) -> list[str]:
    wid = workspace_id_for_path(workspace_path)
    if wid is None:
        return []
    lm = _coerce_str_list(llm_models)
    vm = _coerce_str_list(voice_models)
    svc = build_available_models_service(workspace_path, wid)
    v = svc.validate_character_models(lm, vm)
    return character_model_validation_warnings(v)


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


def _parse_json_voice_provider_map_optional(label: str, raw: str | None) -> dict[str, str] | None:
    """Parse optional JSON object mapping provider_id → voice preset id; None means omit."""
    if raw is None:
        return None
    if not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for {label}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} must be a JSON object.")
    out: dict[str, str] = {}
    for k, v in data.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise ValueError(f"{label} must map string keys to string values.")
        kk = k.strip()
        vv = v.strip()
        if kk and vv:
            out[kk] = vv
    return out


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
        "llm_models_json": ToolParam(
            str,
            'JSON array of preferred LLM ids, e.g. ["openai:gpt-5.4"]',
            required=False,
        ),
        "voice_models_json": ToolParam(
            str,
            'JSON array of preferred voice ids',
            required=False,
        ),
        "tts_instructions": ToolParam(
            str,
            "Optional global TTS style instruction (one string per character).",
            required=False,
        ),
        "tts_voice_by_provider_json": ToolParam(
            str,
            'Optional JSON object mapping catalog provider id to one voice preset, e.g. {"openai":"sage"}',
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
        llm_models_json: str | None = None,
        voice_models_json: str | None = None,
        tts_instructions: str | None = None,
        tts_voice_by_provider_json: str | None = None,
        emotions_enabled: bool | None = None,
        extras_json: str | None = None,
    ) -> CharacterCreateResult:
        workspace_path = _resolve_path(workspace)
        llm_models = _parse_json_string_list("llm_models_json", llm_models_json)
        voice_models = _parse_json_string_list("voice_models_json", voice_models_json)
        extras = _parse_json_object("extras_json", extras_json)
        tts_vp = _parse_json_voice_provider_map_optional(
            "tts_voice_by_provider_json", tts_voice_by_provider_json
        )
        detail = character_domain.create_character(
            workspace_path,
            character_id,
            name,
            description=description or "",
            prompt=prompt,
            backstory=backstory or "",
            llm_models=llm_models,
            voice_models=voice_models,
            tts_instructions=(tts_instructions or "").strip(),
            tts_voice_by_provider=tts_vp if tts_vp is not None else {},
            emotions_enabled=bool(emotions_enabled) if emotions_enabled is not None else False,
            extras=extras,
        )
        warn = _validate_character_model_warnings(
            workspace_path,
            detail.get("llm_models"),
            detail.get("voice_models"),
        )
        return CharacterCreateResult(character=detail, warnings=warn)


class CharacterUpdateTool(Tool):
    name = "character_update"
    description = "Update an existing character; only provided fields are changed"
    params = {
        "character_id": ToolParam(str, "Character id to update"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
        "name": ToolParam(str, "Display name", required=False),
        "description": ToolParam(str, "Short profile description", required=False),
        "prompt": ToolParam(str, "System prompt (persona) markdown body", required=False),
        "backstory": ToolParam(str, "Static backstory markdown", required=False),
        "llm_models_json": ToolParam(str, "JSON array of preferred LLM ids", required=False),
        "voice_models_json": ToolParam(str, "JSON array of preferred voice ids", required=False),
        "tts_instructions": ToolParam(
            str,
            "Optional global TTS style instruction for this character.",
            required=False,
        ),
        "tts_voice_by_provider_json": ToolParam(
            str,
            'Optional JSON object: provider id → voice preset (replaces map when set)',
            required=False,
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
        llm_models_json: str | None = None,
        voice_models_json: str | None = None,
        tts_instructions: str | None = None,
        tts_voice_by_provider_json: str | None = None,
        emotions_enabled: bool | None = None,
        extras_json: str | None = None,
    ) -> CharacterUpdateResult:
        workspace_path = _resolve_path(workspace)
        llm_models = _parse_json_string_list("llm_models_json", llm_models_json)
        voice_models = _parse_json_string_list("voice_models_json", voice_models_json)
        extras = _parse_json_object("extras_json", extras_json)
        tts_vp: dict[str, str] | None = None
        if tts_voice_by_provider_json is not None:
            tts_vp = _parse_json_voice_provider_map_optional(
                "tts_voice_by_provider_json", tts_voice_by_provider_json
            )
        detail = character_domain.update_character(
            workspace_path,
            character_id,
            name=name,
            description=description,
            prompt=prompt,
            backstory=backstory,
            llm_models=llm_models,
            voice_models=voice_models,
            tts_instructions=tts_instructions.strip() if tts_instructions is not None else None,
            tts_voice_by_provider=tts_vp,
            emotions_enabled=emotions_enabled,
            extras=extras,
        )
        warn = _validate_character_model_warnings(
            workspace_path,
            detail.get("llm_models"),
            detail.get("voice_models"),
        )
        return CharacterUpdateResult(character=detail, warnings=warn)


class CharacterDeleteTool(Tool):
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
