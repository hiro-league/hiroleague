"""Character management for the admin API."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from hirocli.domain.character import character_dir, character_photo_media_type, load_character_from_disk
from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.preferences import (
    AiProfile,
    VoiceProfile,
    WorkspacePreferences,
    load_preferences,
    profile_model_available,
    resolve_character_llm,
    resolve_character_voice,
    voice_profile_usable,
)
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

# Phase 7b step 5: a character's rows are its AI / voice profiles (were catalog model ids).
AiRowStatus = Literal["available", "unavailable", "plan", "missing"]
VoiceRowStatus = Literal["available", "no_key", "missing"]


def _dedupe_preserve_order(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(i for i in ids if i))


def _ai_row(prefs: WorkspacePreferences, store: CredentialStore, profile_id: str) -> dict[str, Any]:
    """One AI profile as the resolution view shows it (status: can it answer now?)."""
    profile: AiProfile | None = prefs.ai.profiles.get(profile_id)
    if profile is None:
        return {"profile_id": profile_id, "label": None, "model": None, "status": "missing"}
    status: AiRowStatus
    if profile.is_plan:
        status = "plan"
    elif profile_model_available(profile.model, store):
        status = "available"
    else:
        status = "unavailable"
    return {
        "profile_id": profile_id,
        "label": profile.label,
        "model": profile.model,
        "status": status,
        "fallback": profile.fallback,
    }


def _voice_row(prefs: WorkspacePreferences, store: CredentialStore, profile_id: str) -> dict[str, Any]:
    """One voice profile as the resolution view shows it (status: does its provider have a key?)."""
    voice: VoiceProfile | None = prefs.voice.profiles.get(profile_id)
    if voice is None:
        return {"profile_id": profile_id, "label": None, "model": None, "voice": None, "status": "missing"}
    status: VoiceRowStatus = "available" if voice_profile_usable(voice, store) else "no_key"
    return {
        "profile_id": profile_id,
        "label": voice.label,
        "model": voice.model,
        "voice": voice.voice_label or voice.voice,
        "status": status,
    }


@dataclass
class CharacterSavePayload:
    """Result of create/update including post-save model validation warnings."""

    character: dict[str, Any]
    warnings: list[str]


def _chain(prefs: WorkspacePreferences, profile_id: str) -> list[str]:
    from hirocli.domain.preferences import ai_fallback_chain

    return ai_fallback_chain(prefs.ai.profiles, profile_id)


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
                                mime = character_photo_media_type(ch.photo_filename)
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
            mime = character_photo_media_type(ch.photo_filename)
            return Result.success(f"data:{mime};base64,{base64.b64encode(data).decode()}")
        except FileNotFoundError as exc:
            return Result.failure(str(exc))
        except OSError as exc:
            return Result.failure(str(exc))

    def get_character_resolved_configuration(
        self,
        workspace_id: str | None,
        character_id: str,
    ) -> Result[dict[str, Any]]:
        """How the runtime would resolve chat/voice for this character (Phase 7 admin UX; Phase 7b
        step 5: from its AI / voice profiles, then Hiro's chat profile / Hiro's own voice)."""
        if not workspace_id:
            return Result.failure("No workspace selected.")
        cid = character_id.strip()
        if not cid:
            return Result.failure("Character id is required.")
        try:
            entry, _ = resolve_workspace(workspace_id)
            wp = Path(entry.path)
            raw = CharacterGetTool().execute(character_id=cid, workspace=workspace_id)
        except FileNotFoundError as exc:
            return Result.failure(str(exc))
        except Exception as exc:
            return Result.failure(str(exc))
        ch = dict(raw.character)
        ai_ids = [str(x) for x in ch.get("ai_profiles") or [] if isinstance(x, str)]
        voice_ids = [str(x) for x in ch.get("voice_profiles") or [] if isinstance(x, str)]

        prefs = load_preferences(wp)
        store = CredentialStore(wp, workspace_id)

        ai_rows = [_ai_row(prefs, store, pid) for pid in _dedupe_preserve_order(ai_ids)]
        chat_pid = prefs.llm.chat_profile
        ai_workspace_row = _ai_row(prefs, store, chat_pid) if chat_pid else None
        resolved_llm = resolve_character_llm(ai_ids, prefs, wp, workspace_id=workspace_id, credential_store=store)
        ai_applied: dict[str, Any] | None = None
        if resolved_llm is not None:
            # "character" when the model came from one of the character's profiles (or their fallbacks).
            from_character = any(
                resolved_llm.profile_id in _chain(prefs, pid) for pid in ai_ids if pid in prefs.ai.profiles
            )
            ai_applied = {
                "source": "character" if from_character else "workspace_fallback",
                "profile_id": resolved_llm.profile_id or None,
                "profile_label": resolved_llm.profile_name or None,
                "model_id": resolved_llm.model_id,
                "temperature": resolved_llm.temperature,
                "max_tokens": resolved_llm.max_tokens,
                "thinking": resolved_llm.thinking,
                "num_ctx": resolved_llm.num_ctx,
            }

        voice_rows = [_voice_row(prefs, store, pid) for pid in _dedupe_preserve_order(voice_ids)]
        hiro_pid = prefs.voice.hiro_profile
        voice_workspace_row = _voice_row(prefs, store, hiro_pid) if hiro_pid else None
        voice_disabled = not prefs.media.output.voice
        voice_applied: dict[str, Any] | None = None
        if not voice_disabled:
            resolved_voice = resolve_character_voice(
                voice_ids, prefs, wp, workspace_id=workspace_id, credential_store=store
            )
            if resolved_voice is not None:
                voice_applied = {
                    "source": resolved_voice.source,
                    "profile_id": resolved_voice.profile_id,
                    "label": resolved_voice.profile.label,
                    "model": resolved_voice.profile.model,
                    "voice": resolved_voice.profile.voice,
                    "style": resolved_voice.profile.style,
                }

        payload: dict[str, Any] = {
            "character_id": ch.get("id", cid),
            "ai_rows": ai_rows,
            "ai_workspace_row": ai_workspace_row,
            "ai_applied": ai_applied,
            "voice_rows": voice_rows,
            "voice_workspace_row": voice_workspace_row,
            "voice_applied": voice_applied,
            "voice_disabled": voice_disabled,
        }
        return Result.success(payload)

    def create_character(
        self,
        workspace_id: str | None,
        *,
        character_id: str,
        name: str,
        description: str = "",
        prompt: str | None = None,
        backstory: str = "",
        ai_profiles_json: str = "",
        voice_profiles_json: str = "",
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
                ai_profiles_json=ai_profiles_json or None,
                voice_profiles_json=voice_profiles_json or None,
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
        ai_profiles_json: str | None = None,
        voice_profiles_json: str | None = None,
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
        if ai_profiles_json is not None:
            kwargs["ai_profiles_json"] = ai_profiles_json
        if voice_profiles_json is not None:
            kwargs["voice_profiles_json"] = voice_profiles_json
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
