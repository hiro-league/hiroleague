"""Character admin routes."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from hirocli.admin.features.characters.service import CharacterService
from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.photo_decode import _decode_photo_data_url
from hirocli.admin_svelte.result_payload import _api_from_result, envelope_failure
from hirocli.admin_svelte.schemas import CharacterPhotoUploadRequest, CharacterSaveRequest

characters_router = APIRouter()


def _character_save_payload(data: Any) -> dict[str, Any]:
    return {
        "character": getattr(data, "character", {}),
        "warnings": list(getattr(data, "warnings", [])),
    }


@characters_router.get("/characters")
async def list_characters(workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    result = await run_in_threadpool(
        CharacterService().list_characters_with_preview_images,
        workspace_id,
    )
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    return payload


@characters_router.post("/characters")
async def create_character(
    body: CharacterSaveRequest,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(
            CharacterService().create_character,
            workspace_id,
            character_id=body.character_id or "",
            name=body.name,
            description=body.description,
            prompt=body.prompt,
            backstory=body.backstory,
            llm_models_json=body.llm_models_json,
            tuning_profile=body.tuning_profile,
            voice_models_json=body.voice_models_json,
            tts_instructions=body.tts_instructions,
            tts_voice_by_provider_json=body.tts_voice_by_provider_json,
            emotions_enabled=body.emotions_enabled,
            extras_json=body.extras_json,
        )
    )
    if not result.ok or result.data is None:
        return _api_from_result(result)
    return {"ok": True, "error": None, "data": _character_save_payload(result.data)}


@characters_router.get("/characters/{character_id}")
async def get_character(
    character_id: str,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    result = await run_in_threadpool(
        CharacterService().get_character,
        workspace_id,
        character_id,
    )
    if not result.ok or result.data is None:
        return _api_from_result(result)
    data = dict(result.data)
    photo = await run_in_threadpool(
        CharacterService().character_detail_photo_data_url,
        workspace_id,
        character_id,
    )
    data["photo_data_url"] = photo.data if photo.ok else None
    data["photo_error"] = photo.error if not photo.ok else None
    return {"ok": True, "error": None, "data": data}


@characters_router.get("/characters/{character_id}/resolved")
async def get_character_resolved(
    character_id: str,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    """Phase 7: runtime resolution preview (catalog + credentials vs character lists)."""
    result = await run_in_threadpool(
        CharacterService().get_character_resolved_configuration,
        workspace_id,
        character_id,
    )
    return _api_from_result(result)


@characters_router.patch("/characters/{character_id}")
async def update_character(
    character_id: str,
    body: CharacterSaveRequest,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(
            CharacterService().update_character,
            workspace_id,
            character_id,
            name=body.name,
            description=body.description,
            prompt=body.prompt,
            backstory=body.backstory,
            llm_models_json=body.llm_models_json,
            tuning_profile=body.tuning_profile,
            voice_models_json=body.voice_models_json,
            tts_instructions=body.tts_instructions,
            tts_voice_by_provider_json=body.tts_voice_by_provider_json,
            emotions_enabled=body.emotions_enabled,
            extras_json=body.extras_json,
        )
    )
    if not result.ok or result.data is None:
        return _api_from_result(result)
    return {"ok": True, "error": None, "data": _character_save_payload(result.data)}


@characters_router.delete("/characters/{character_id}")
async def delete_character(
    character_id: str,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    result = await run_in_threadpool(
        CharacterService().delete_character,
        workspace_id,
        character_id,
    )
    return _api_from_result(result)


@characters_router.post("/characters/{character_id}/photo")
async def upload_character_photo(
    character_id: str,
    body: CharacterPhotoUploadRequest,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    try:
        raw = _decode_photo_data_url(body.data_url)
    except ValueError as exc:
        return envelope_failure(str(exc))
    with NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    try:
        result = await run_in_threadpool(
            CharacterService().upload_photo,
            workspace_id,
            character_id,
            tmp_path,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return _api_from_result(result)
