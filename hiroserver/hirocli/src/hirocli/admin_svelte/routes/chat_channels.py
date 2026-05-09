"""Chat channel admin routes."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from hirocli.admin.features.chat_channels.service import ChatChannelsService
from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.photo_decode import _decode_photo_data_url
from hirocli.admin_svelte.result_payload import _api_from_result, envelope_failure
from hirocli.admin_svelte.schemas import ChatChannelPhotoUploadRequest, ChatChannelSaveRequest

chat_channels_router = APIRouter()


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


@chat_channels_router.get("/chat-channels/{channel_id}/messages")
async def list_chat_channel_messages(
    channel_id: int,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ChatChannelsService().list_messages_all,
        workspace_id,
        channel_id,
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
