"""Voice routes (Phase 7b) — the Catalog's Voice profiles tab over the voice tools (tools/voice.py).

Profiles are created, changed and deleted through the preferences API (``voice.profiles.<id>``, like
``ai.profiles``); these routes read them, list Gemini's voices, design / add / delete our own, Try a
profile, manage ``voice.uses`` and read the clip cache. Audio comes back as OGG: a voice's sample, and a
Try it take (to play or download); a take can also be sent to a family member as a WhatsApp voice note.
"""

from __future__ import annotations

import base64
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Request, Response
from hiro_channel_sdk.constants import WHATSAPP_CALL_SEND
from hiro_commons.log import Logger
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import envelope_failure
from hirocli.admin_svelte.routes.ai import _ok, _workspace_path
from hirocli.domain.people import get_person
from hirocli.domain.workspace import WorkspaceError
from hirocli.runtime.preferences_runtime import PreferencePathError
from hirocli.services.voice import VoiceError, kept, sample
from hirocli.tools.voice import (
    VoiceAddTool,
    VoiceCatalogTool,
    VoiceClipCacheTool,
    VoiceDeleteTool,
    VoiceDesignTool,
    VoiceProfilesListTool,
    VoiceTryTool,
    VoiceUsesListTool,
    VoiceUsesSetTool,
    VoiceVoicesTool,
)

log = Logger.get("ADMIN.VOICE")

voice_router = APIRouter()

WHATSAPP_CHANNEL = "whatsapp"
SEND_TIMEOUT_S = 50.0


class VoiceDesignBody(BaseModel):
    name: str
    description: str
    language: str | None = None
    gender: str | None = None


class VoiceIdBody(BaseModel):
    voice_id: str


class VoiceTryBody(BaseModel):
    text: str
    profile_id: str | None = None
    draft: dict[str, Any] | None = None  # a profile not saved yet (voice profile fields)


class VoiceUseBody(BaseModel):
    profile_id: str | None = None


class ClipSendBody(BaseModel):
    person_id: str


def _failure(exc: Exception) -> dict[str, Any]:
    message = exc.message if isinstance(exc, VoiceError) else str(exc)
    return envelope_failure(message)


_ERRORS = (VoiceError, WorkspaceError, ValueError, OSError)


@voice_router.get("/voice/profiles")
async def voice_profiles(workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    try:
        return _ok(asdict(await VoiceProfilesListTool().execute_async(workspace=workspace_id)))
    except _ERRORS as exc:
        return _failure(exc)


@voice_router.get("/voice/catalog")
async def voice_catalog(workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    try:
        return _ok(asdict(await run_in_threadpool(VoiceCatalogTool().execute, workspace=workspace_id)))
    except _ERRORS as exc:
        return _failure(exc)


@voice_router.get("/voice/voices")
async def voice_voices(
    workspace_id: SelectedWorkspaceIdDep,
    source: str | None = None,
    language: str | None = None,
    gender: str | None = None,
    q: str | None = None,
    limit: int = 60,
    refresh: bool = False,
) -> dict[str, Any]:
    try:
        result = await VoiceVoicesTool().execute_async(
            source=source, language=language, gender=gender, q=q, limit=limit, refresh=refresh, workspace=workspace_id
        )
        return _ok(asdict(result))
    except _ERRORS as exc:
        return _failure(exc)


@voice_router.get("/voice/voices/{voice_id}/sample")
async def voice_sample(voice_id: str, workspace_id: SelectedWorkspaceIdDep) -> Response:
    path = _workspace_path(workspace_id)
    if path is None:
        return Response(status_code=404)
    try:
        ogg, paid = await sample(path, voice_id)
    except VoiceError as exc:
        return Response(exc.message, status_code=exc.status, media_type="text/plain")
    if paid is not None:
        from hirocli.services.ai_usage import HIRO_SOURCE, UsageCall, record_async
        from hirocli.services.voice.engine import SAMPLE_MODEL

        await record_async(
            path,
            UsageCall(kind="speech", source=HIRO_SOURCE, use="voice_samples", provider="google", model=SAMPLE_MODEL,
                      tokens_in=paid.tokens_in, tokens_out=paid.tokens_out, cost=paid.cost_usd or 0.0,
                      unpriced=int(paid.cost_usd is None)),
        )
    return Response(ogg, media_type="audio/ogg", headers={"Cache-Control": "private, max-age=86400"})


@voice_router.post("/voice/voices")
async def voice_design(body: VoiceDesignBody, workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    try:
        result = await VoiceDesignTool().execute_async(
            name=body.name, description=body.description, language=body.language, gender=body.gender,
            workspace=workspace_id,
        )
        return _ok(asdict(result))
    except _ERRORS as exc:
        return _failure(exc)


@voice_router.post("/voice/voices/add")
async def voice_add(body: VoiceIdBody, workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    try:
        return _ok(asdict(await VoiceAddTool().execute_async(voice_id=body.voice_id, workspace=workspace_id)))
    except _ERRORS as exc:
        return _failure(exc)


@voice_router.delete("/voice/voices/{voice_id}")
async def voice_delete(voice_id: str, workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    try:
        return _ok(asdict(await VoiceDeleteTool().execute_async(voice_id=voice_id, workspace=workspace_id)))
    except _ERRORS as exc:
        return _failure(exc)


@voice_router.post("/voice/try")
async def voice_try(body: VoiceTryBody, workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    try:
        result = await VoiceTryTool().execute_async(
            text=body.text, profile_id=body.profile_id, draft=body.draft, workspace=workspace_id
        )
        return _ok(asdict(result))
    except _ERRORS as exc:
        return _failure(exc)


@voice_router.get("/voice/clips/{clip_id}.ogg")
async def voice_clip(clip_id: str, download: bool = False) -> Response:
    clip = kept(clip_id)
    if clip is None:
        return Response("This take is gone (only the last 30 are kept).", status_code=404, media_type="text/plain")
    headers = {"Cache-Control": "private, max-age=3600"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="hiro-voice-{clip_id[:8]}.ogg"'
    return Response(clip.ogg, media_type="audio/ogg", headers=headers)


@voice_router.post("/voice/clips/{clip_id}/send")
async def voice_clip_send(
    clip_id: str, body: ClipSendBody, request: Request, workspace_id: SelectedWorkspaceIdDep
) -> dict[str, Any]:
    """Send a Try it take to a family member as a WhatsApp voice note (through the core's WhatsApp)."""
    path = _workspace_path(workspace_id)
    clip = kept(clip_id)
    if path is None or clip is None:
        return envelope_failure("This take is gone (only the last 30 are kept).")
    person = await run_in_threadpool(get_person, path, body.person_id)
    if person is None or not person.whatsapp:
        return envelope_failure("That person has no WhatsApp number in the family list.")
    ctx = getattr(request.app.state, "ctx", None)
    channels = getattr(ctx, "channel_manager", None) if ctx is not None else None
    if channels is None:
        return envelope_failure("WhatsApp isn't running in HiroLeague.")
    send = {
        "to": person.whatsapp,
        "voice_b64": base64.b64encode(clip.ogg).decode("ascii"),
        "voice_seconds": clip.seconds,
        "waveform_b64": base64.b64encode(clip.waveform).decode("ascii"),
    }
    try:
        await channels.call_channel(WHATSAPP_CHANNEL, WHATSAPP_CALL_SEND, send, timeout=SEND_TIMEOUT_S)
    except Exception as exc:  # the plugin's refusal or a dropped call: shown as is
        log.warning(f"⚠️ Voice note not sent — {person.name}", error=str(exc))
        return envelope_failure(f"Not sent: {exc}")
    log.info(f"⬆️ Voice note sent — {person.name} · Try it take", seconds=round(clip.seconds, 1))
    return _ok({"sent": True, "name": person.name})


@voice_router.get("/voice/uses")
async def voice_uses(workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    try:
        return _ok(asdict(await run_in_threadpool(VoiceUsesListTool().execute, workspace=workspace_id)))
    except _ERRORS as exc:
        return _failure(exc)


@voice_router.put("/voice/uses/{key}")
async def voice_use_set(key: str, body: VoiceUseBody, workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    try:
        result = await run_in_threadpool(
            VoiceUsesSetTool().execute, key=key, profile_id=body.profile_id, workspace=workspace_id
        )
        return _ok(asdict(result))
    except (*_ERRORS, PreferencePathError) as exc:
        return _failure(exc)


@voice_router.get("/voice/clip-cache")
async def voice_clip_cache(workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    try:
        return _ok(asdict(await run_in_threadpool(VoiceClipCacheTool().execute, workspace=workspace_id)))
    except _ERRORS as exc:
        return _failure(exc)
