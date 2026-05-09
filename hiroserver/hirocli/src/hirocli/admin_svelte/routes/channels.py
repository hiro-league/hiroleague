"""Workspace channel enable/disable routes (non-chat channels)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME
from hirocli.admin.features.channels.service import ChannelService
from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import _api_from_result

channels_router = APIRouter()


@channels_router.get("/channels")
async def list_channels(workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    result = await run_in_threadpool(
        ChannelService().list_channels,
        workspace_id,
    )
    if not result.ok:
        return _api_from_result(result)
    return {
        "ok": True,
        "error": None,
        "data": {
            "channels": result.data or [],
            "mandatory_channel_name": MANDATORY_CHANNEL_NAME,
        },
    }


@channels_router.post("/channels/{channel_name}/enable")
async def enable_channel(
    channel_name: str,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ChannelService().enable_channel,
        channel_name,
        workspace_id,
    )
    return _api_from_result(result)


@channels_router.post("/channels/{channel_name}/disable")
async def disable_channel(
    channel_name: str,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ChannelService().disable_channel,
        channel_name,
        workspace_id,
    )
    return _api_from_result(result)
