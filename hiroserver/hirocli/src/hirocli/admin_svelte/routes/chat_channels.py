"""Chat channel admin routes."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from hirocli.admin.features.chat_channels.service import ChatChannelsService
from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.photo_decode import _decode_photo_data_url
from hirocli.admin_svelte.result_payload import _api_from_result, envelope_failure
from hirocli.admin_svelte.schemas import ChatChannelMessageSendRequest, ChatChannelPhotoUploadRequest, ChatChannelSaveRequest

chat_channels_router = APIRouter()

_MAX_MESSAGE_PK_RESYNC = 16


@chat_channels_router.get("/chat-channels")
async def list_chat_channels(workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    result = await run_in_threadpool(
        ChatChannelsService().list_channels,
        workspace_id,
    )
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    return payload


@chat_channels_router.post("/chat-channels")
async def create_chat_channel(
    body: ChatChannelSaveRequest,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(
            ChatChannelsService().create_channel,
            workspace_id,
            name=body.name,
            character_id=body.character_id,
            description=body.description,
        )
    )
    return _api_from_result(result)


@chat_channels_router.patch("/chat-channels/{channel_id}")
async def update_chat_channel(
    channel_id: int,
    body: ChatChannelSaveRequest,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(
            ChatChannelsService().update_channel,
            workspace_id,
            channel_id,
            name=body.name,
            character_id=body.character_id,
            description=body.description,
        )
    )
    return _api_from_result(result)


@chat_channels_router.delete("/chat-channels/{channel_id}")
async def delete_chat_channel(
    channel_id: int,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ChatChannelsService().delete_channel,
        workspace_id,
        channel_id,
    )
    return _api_from_result(result)


@chat_channels_router.post("/chat-channels/{channel_id}/messages/clear")
async def clear_chat_channel_messages(
    channel_id: int,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ChatChannelsService().clear_messages,
        workspace_id,
        channel_id,
    )
    return _api_from_result(result)


@chat_channels_router.post("/chat-channels/{channel_id}/messages/send")
async def send_chat_channel_message(
    channel_id: int,
    body: ChatChannelMessageSendRequest,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    """Proxy to workspace Hiro ``POST /invoke`` → ``message_send`` (live server)."""
    result = await run_in_threadpool(
        partial(
            ChatChannelsService().send_chat_message,
            workspace_id,
            channel_id,
            text=body.text,
            audio_base64=body.audio_base64,
            audio_mime_type=body.audio_mime_type,
            audio_duration_ms=body.audio_duration_ms,
            request_voice_reply=body.request_voice_reply,
            use_knowledge=body.use_knowledge,
        )
    )
    return _api_from_result(result)


@chat_channels_router.get("/chat-channels/{channel_id}/messages")
async def list_chat_channel_messages(
    channel_id: int,
    workspace_id: SelectedWorkspaceIdDep,
    after: str | None = None,
    after_id: str | None = None,
    limit: int | None = None,
    message_pk: list[int] | None = Query(default=None),
) -> dict[str, Any]:
    has_cursor_param = after is not None or after_id is not None
    has_message_pk = message_pk is not None and len(message_pk) > 0
    if has_message_pk and (has_cursor_param or limit is not None):
        raise HTTPException(
            status_code=400,
            detail="message_pk cannot be combined with cursor or limit parameters.",
        )
    if has_message_pk and len(message_pk) > _MAX_MESSAGE_PK_RESYNC:
        raise HTTPException(
            status_code=400,
            detail=f"message_pk is limited to {_MAX_MESSAGE_PK_RESYNC} values.",
        )
    if (after is None) != (after_id is None):
        raise HTTPException(
            status_code=400,
            detail="after and after_id must be provided together.",
        )
    if has_cursor_param and limit is None:
        raise HTTPException(
            status_code=400,
            detail="limit is required with after and after_id.",
        )
    if limit is not None and not has_cursor_param:
        raise HTTPException(
            status_code=400,
            detail="limit is only supported with after and after_id.",
        )
    if limit is not None and limit < 1:
        raise HTTPException(status_code=400, detail="limit must be positive.")

    result = await run_in_threadpool(
        partial(
            ChatChannelsService().list_messages_all,
            workspace_id,
            channel_id,
            after=after,
            after_id=after_id,
            limit=limit,
            message_pks=message_pk if has_message_pk else None,
        )
    )
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    return payload


@chat_channels_router.get(
    "/chat-channels/{channel_id}/messages/by-external/{external_message_id}/attachments/{slot}/media",
)
async def get_chat_message_attachment_media(
    channel_id: int,
    external_message_id: str,
    slot: int,
    workspace_id: SelectedWorkspaceIdDep,
) -> FileResponse:
    """Stream one message attachment for admin `<audio>` playback (workspace-scoped)."""
    if slot < 0:
        raise HTTPException(status_code=400, detail="Invalid attachment slot.")
    result = await run_in_threadpool(
        partial(
            ChatChannelsService().resolve_message_attachment_media,
            workspace_id,
            channel_id,
            external_message_id,
            slot,
        )
    )
    if not result.ok or result.data is None:
        raise HTTPException(
            status_code=404,
            detail=result.error or "Attachment not found.",
        )
    path_str, media_type = result.data
    return FileResponse(path_str, media_type=media_type)


@chat_channels_router.post("/chat-channels/{channel_id}/photo")
async def upload_chat_channel_photo(
    channel_id: int,
    body: ChatChannelPhotoUploadRequest,
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
            ChatChannelsService().upload_channel_photo,
            workspace_id,
            channel_id,
            tmp_path,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return _api_from_result(result)
