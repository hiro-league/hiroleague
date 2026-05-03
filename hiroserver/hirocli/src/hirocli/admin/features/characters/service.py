"""Character management for the admin API."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from hirocli.domain.available_models import AvailableModelsService
from hirocli.domain.character import character_dir, character_photo_media_type, load_character_from_disk
from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.model_catalog import get_model_catalog
from hirocli.domain.preferences import (
    WorkspacePreferences,
    load_preferences,
    resolve_character_llm,
    resolve_character_voice,
    resolve_llm,
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

RowStatus = Literal["available", "unavailable", "unknown", "wrong_kind", "deprecated"]


def _llm_row_status(cat: Any, ams: AvailableModelsService, model_id: str) -> RowStatus:
    spec = cat.get_model(model_id)
    if spec is None:
        return "unknown"
    if spec.deprecated_since:
        return "deprecated"
    if spec.model_kind != "chat":
        return "wrong_kind"
    if not ams.is_model_available(model_id):
        return "unavailable"
    return "available"


def _voice_row_status(cat: Any, ams: AvailableModelsService, model_id: str) -> RowStatus:
    """Classify a character ``voice_models`` entry for TTS resolution (STT → wrong_kind)."""
    spec = cat.get_model(model_id)
    if spec is None:
        return "unknown"
    if spec.deprecated_since:
        return "deprecated"
    if spec.model_kind != "tts":
        return "wrong_kind"
    if not ams.is_model_available(model_id):
        return "unavailable"
    return "available"


def _preference_workspace_chat_row(
    prefs: WorkspacePreferences,
    cat: Any,
    ams: AvailableModelsService,
) -> dict[str, Any] | None:
    """Single row describing ``llm.default_chat`` for admin resolution UX (alongside character list)."""
    mid = str(prefs.llm.default_chat or "").strip()
    if not mid:
        return None
    spec = cat.get_model(mid)
    st = _llm_row_status(cat, ams, mid)
    row: dict[str, Any] = {
        "model_id": mid,
        "status": st,
        "display_name": spec.display_name if spec is not None else None,
    }
    if st == "deprecated" and spec is not None:
        row["replacement_id"] = spec.replacement_id
    return row


def _preference_workspace_tts_row(
    prefs: WorkspacePreferences,
    cat: Any,
    ams: AvailableModelsService,
) -> dict[str, Any] | None:
    """Single row describing ``llm.default_tts`` for admin resolution UX."""
    mid = str(prefs.llm.default_tts or "").strip()
    if not mid:
        return None
    spec = cat.get_model(mid)
    st = _voice_row_status(cat, ams, mid)
    row: dict[str, Any] = {
        "model_id": mid,
        "status": st,
        "display_name": spec.display_name if spec is not None else None,
    }
    if st == "deprecated" and spec is not None:
        row["replacement_id"] = spec.replacement_id
    if spec is not None and spec.model_kind == "stt":
        row["note"] = "STT model — not used for reply TTS; pick a TTS model for voice replies."
    return row


def _dedupe_preserve_order(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for mid in ids:
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append(mid)
    return out


def _first_available_chat_from_character_list(
    ordered_model_ids: list[str],
    cat: Any,
    ams: AvailableModelsService,
) -> tuple[str | None, int | None]:
    """First chat model id the runtime would take from the character list; list index in original order."""
    seen: set[str] = set()
    for idx, mid in enumerate(ordered_model_ids):
        if not mid or mid in seen:
            continue
        seen.add(mid)
        spec = cat.get_model(mid)
        if spec is None or spec.model_kind != "chat":
            continue
        if not ams.is_model_available(mid):
            continue
        return mid, idx
    return None, None


def _first_available_tts_from_character_list(
    ordered_model_ids: list[str],
    cat: Any,
    ams: AvailableModelsService,
) -> tuple[str | None, int | None]:
    seen: set[str] = set()
    for idx, mid in enumerate(ordered_model_ids):
        if not mid or mid in seen:
            continue
        seen.add(mid)
        spec = cat.get_model(mid)
        if spec is None or spec.model_kind != "tts":
            continue
        if not ams.is_model_available(mid):
            continue
        return mid, idx
    return None, None


@dataclass
class CharacterSavePayload:
    """Result of create/update including post-save model validation warnings."""

    character: dict[str, Any]
    warnings: list[str]


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
        """How the runtime would resolve chat/TTS for this character (Phase 7 admin UX)."""
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
        llm_models = ch.get("llm_models") if isinstance(ch.get("llm_models"), list) else []
        voice_models = ch.get("voice_models") if isinstance(ch.get("voice_models"), list) else []
        llm_models = [str(x) for x in llm_models]
        voice_models = [str(x) for x in voice_models]
        tts_instructions = str(ch.get("tts_instructions") or "")
        vm_raw = ch.get("tts_voice_by_provider")
        tts_voice_by_provider: dict[str, str] | None = None
        if isinstance(vm_raw, dict):
            tts_voice_by_provider = {
                str(k): str(v) for k, v in vm_raw.items() if isinstance(k, str) and isinstance(v, str)
            }

        prefs = load_preferences(wp)
        cat = get_model_catalog()
        store = CredentialStore(wp, workspace_id)
        ams = AvailableModelsService(cat, store)

        llm_rows: list[dict[str, Any]] = []
        for mid in _dedupe_preserve_order(llm_models):
            spec = cat.get_model(mid)
            st = _llm_row_status(cat, ams, mid)
            row: dict[str, Any] = {
                "model_id": mid,
                "status": st,
                "display_name": spec.display_name if spec is not None else None,
            }
            if st == "deprecated" and spec is not None:
                row["replacement_id"] = spec.replacement_id
            llm_rows.append(row)

        llm_workspace_row = _preference_workspace_chat_row(prefs, cat, ams)

        resolved_llm = resolve_character_llm(
            llm_models,
            prefs,
            wp,
            workspace_id=workspace_id,
            credential_store=store,
        )
        first_llm, _llm_idx = _first_available_chat_from_character_list(llm_models, cat, ams)
        if not llm_models:
            llm_source: Literal["character", "workspace_fallback"] = "workspace_fallback"
        elif first_llm and resolved_llm is not None and first_llm == resolved_llm.model_id:
            llm_source = "character"
        else:
            llm_source = "workspace_fallback"

        llm_applied: dict[str, Any] | None
        if resolved_llm is None:
            llm_applied = None
        else:
            llm_applied = {
                "source": llm_source,
                "model_id": resolved_llm.model_id,
                "temperature": resolved_llm.temperature,
                "max_tokens": resolved_llm.max_tokens,
            }

        voice_rows: list[dict[str, Any]] = []
        for mid in _dedupe_preserve_order(voice_models):
            spec = cat.get_model(mid)
            st = _voice_row_status(cat, ams, mid)
            row = {
                "model_id": mid,
                "status": st,
                "display_name": spec.display_name if spec is not None else None,
            }
            if st == "deprecated" and spec is not None:
                row["replacement_id"] = spec.replacement_id
            if spec is not None and spec.model_kind == "stt":
                row["note"] = "STT model — not used for reply TTS; pick a TTS model for voice replies."
            voice_rows.append(row)

        voice_workspace_row = _preference_workspace_tts_row(prefs, cat, ams)

        voice_disabled = not prefs.audio.agent_replies_in_voice
        voice_applied: dict[str, Any] | None = None
        if not voice_disabled:
            resolved_voice = resolve_character_voice(
                voice_models,
                prefs,
                wp,
                workspace_id=workspace_id,
                credential_store=store,
                tts_instructions=tts_instructions,
                tts_voice_by_provider=tts_voice_by_provider,
            )
            first_tts, _v_idx = _first_available_tts_from_character_list(voice_models, cat, ams)
            if not voice_models:
                v_source: Literal["character", "workspace_fallback"] = "workspace_fallback"
            elif (
                first_tts
                and resolved_voice is not None
                and first_tts.split(":", 1)[-1] == resolved_voice.model
            ):
                v_source = "character"
            else:
                v_source = "workspace_fallback"

            catalog_voice_id: str | None = None
            if v_source == "character" and first_tts:
                catalog_voice_id = first_tts
            else:
                tts_entry = resolve_llm(
                    prefs,
                    wp,
                    "tts",
                    workspace_id=workspace_id,
                    credential_store=store,
                )
                catalog_voice_id = tts_entry.model_id if tts_entry is not None else None

            if resolved_voice is not None and catalog_voice_id is not None:
                voice_applied = {
                    "source": v_source,
                    "catalog_model_id": catalog_voice_id,
                    "synthesis": {
                        "model": resolved_voice.model,
                        "voice": resolved_voice.voice,
                        "instructions": resolved_voice.instructions,
                    },
                }

        payload: dict[str, Any] = {
            "character_id": ch.get("id", cid),
            "llm_rows": llm_rows,
            "llm_workspace_row": llm_workspace_row,
            "llm_applied": llm_applied,
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
        llm_models_json: str = "",
        voice_models_json: str = "",
        tts_instructions: str = "",
        tts_voice_by_provider_json: str = "",
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
                tts_instructions=tts_instructions,
                tts_voice_by_provider_json=tts_voice_by_provider_json or None,
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
        tts_instructions: str | None = None,
        tts_voice_by_provider_json: str | None = None,
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
        if tts_instructions is not None:
            kwargs["tts_instructions"] = tts_instructions
        if tts_voice_by_provider_json is not None:
            kwargs["tts_voice_by_provider_json"] = tts_voice_by_provider_json
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
