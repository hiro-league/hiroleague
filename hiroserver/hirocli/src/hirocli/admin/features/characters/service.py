"""Character management — wraps character tools; no NiceGUI (guidelines §1.3)."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hirocli.domain.character import character_dir, load_character_from_disk
from hirocli.domain.workspace import resolve_workspace
from hirocli.tools.character import (
    CharacterCreateTool,
    CharacterDeleteTool,
    CharacterGetTool,
    CharacterListTool,
    CharacterUpdateTool,
    CharacterUploadPhotoTool,
)

from hirocli.admin.shared.result import Result

_MAX_INLINE_PHOTO_BYTES = 2_000_000


@dataclass
class CharacterSavePayload:
    """Result of create/update including post-save model validation warnings."""

    character: dict[str, Any]
    warnings: list[str]


def _mime_for_character_photo(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith(".gif"):
        return "image/gif"
    return "image/png"


class CharacterService:
    """Facade over character tools plus inline photo previews for the admin UI."""

    def list_characters(self, workspace_id: str | None) -> Result[list[dict[str, Any]]]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            raw = CharacterListTool().execute(workspace=workspace_id)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(list(raw.characters))

    def list_characters_with_preview_images(
        self,
        workspace_id: str | None,
    ) -> Result[list[dict[str, Any]]]:
        """List characters and attach optional ``photo_data_url`` for card thumbnails."""
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            entry, _ = resolve_workspace(workspace_id)
            wp = Path(entry.path)
            raw = CharacterListTool().execute(workspace=workspace_id)
            rows: list[dict[str, Any]] = []
            for c in raw.characters:
                row = dict(c)
                url: str | None = None
                if c.get("has_photo") and not c.get("error"):
                    try:
                        ch = load_character_from_disk(wp, c["id"])
                        if ch.photo_filename:
                            path = character_dir(wp, c["id"]) / ch.photo_filename
                            data = path.read_bytes()
                            if len(data) <= _MAX_INLINE_PHOTO_BYTES:
                                mime = _mime_for_character_photo(ch.photo_filename)
                                url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
                    except OSError:
                        url = None
                row["photo_data_url"] = url
                rows.append(row)
            return Result.success(rows)
        except Exception as exc:
            return Result.failure(str(exc))

    def get_character(self, workspace_id: str | None, character_id: str) -> Result[dict[str, Any]]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        if not character_id.strip():
            return Result.failure("Character id is required.")
        try:
            raw = CharacterGetTool().execute(
                character_id=character_id.strip(),
                workspace=workspace_id,
            )
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(dict(raw.character))

    def character_detail_photo_data_url(
        self,
        workspace_id: str | None,
        character_id: str,
    ) -> Result[str | None]:
        """Data URL for the editor header, or None if no photo."""
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            entry, _ = resolve_workspace(workspace_id)
            wp = Path(entry.path)
            ch = load_character_from_disk(wp, character_id.strip())
            if not ch.has_photo or not ch.photo_filename:
                return Result.success(None)
            path = character_dir(wp, character_id.strip()) / ch.photo_filename
            data = path.read_bytes()
            if len(data) > _MAX_INLINE_PHOTO_BYTES:
                return Result.failure("Photo is too large to preview in the browser.")
            mime = _mime_for_character_photo(ch.photo_filename)
            return Result.success(f"data:{mime};base64,{base64.b64encode(data).decode()}")
        except FileNotFoundError as exc:
            return Result.failure(str(exc))
        except OSError as exc:
            return Result.failure(str(exc))

    def create_character(
        self,
        workspace_id: str | None,
        *,
        character_id: str,
        name: str,
        description: str = "",
        prompt: str | None = None,
        backstory: str = "",
        llm_models_json: str = "",
        voice_models_json: str = "",
        emotions_enabled: bool = False,
        extras_json: str = "",
    ) -> Result[CharacterSavePayload]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            raw = CharacterCreateTool().execute(
                character_id=character_id.strip(),
                name=name.strip(),
                workspace=workspace_id,
                description=description or None,
                prompt=prompt,
                backstory=backstory or None,
                llm_models_json=llm_models_json or None,
                voice_models_json=voice_models_json or None,
                emotions_enabled=emotions_enabled,
                extras_json=extras_json or None,
            )
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(
            CharacterSavePayload(character=dict(raw.character), warnings=list(raw.warnings))
        )

    def update_character(
        self,
        workspace_id: str | None,
        character_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        prompt: str | None = None,
        backstory: str | None = None,
        llm_models_json: str | None = None,
        voice_models_json: str | None = None,
        emotions_enabled: bool | None = None,
        extras_json: str | None = None,
    ) -> Result[CharacterSavePayload]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        kwargs: dict[str, Any] = {
            "character_id": character_id.strip(),
            "workspace": workspace_id,
        }
        if name is not None:
            kwargs["name"] = name
        if description is not None:
            kwargs["description"] = description
        if prompt is not None:
            kwargs["prompt"] = prompt
        if backstory is not None:
            kwargs["backstory"] = backstory
        if llm_models_json is not None:
            kwargs["llm_models_json"] = llm_models_json
        if voice_models_json is not None:
            kwargs["voice_models_json"] = voice_models_json
        if emotions_enabled is not None:
            kwargs["emotions_enabled"] = emotions_enabled
        if extras_json is not None:
            kwargs["extras_json"] = extras_json
        try:
            raw = CharacterUpdateTool().execute(**kwargs)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(
            CharacterSavePayload(character=dict(raw.character), warnings=list(raw.warnings))
        )

    def delete_character(self, workspace_id: str | None, character_id: str) -> Result[bool]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            raw = CharacterDeleteTool().execute(
                character_id=character_id.strip(),
                workspace=workspace_id,
            )
        except Exception as exc:
            return Result.failure(str(exc))
        if not raw.deleted:
            return Result.failure(f"Character '{character_id}' was not found.")
        return Result.success(True)

    def upload_photo(
        self,
        workspace_id: str | None,
        character_id: str,
        photo_path: str,
    ) -> Result[str]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        path = Path(photo_path).expanduser().resolve()
        try:
            raw = CharacterUploadPhotoTool().execute(
                character_id=character_id.strip(),
                photo_path=str(path),
                workspace=workspace_id,
            )
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(raw.photo_filename)

    @staticmethod
    def validate_optional_json_array(label: str, raw: str) -> Result[None]:
        if not raw.strip():
            return Result.success(None)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return Result.failure(f"{label}: invalid JSON ({exc})")
        if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
            return Result.failure(f"{label} must be a JSON array of strings.")
        return Result.success(None)

    @staticmethod
    def validate_optional_json_object(label: str, raw: str) -> Result[None]:
        if not raw.strip():
            return Result.success(None)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return Result.failure(f"{label}: invalid JSON ({exc})")
        if not isinstance(data, dict):
            return Result.failure(f"{label} must be a JSON object.")
        return Result.success(None)
