"""Paired device listing and pairing-code routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from hirocli.admin.features.devices.service import DeviceService
from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import _api_data, _api_list
from hirocli.qr_rendering import render_qr_svg

devices_router = APIRouter()


@devices_router.get("/devices")
async def list_devices(workspace_id: SelectedWorkspaceIdDep) -> Any:
    result = await run_in_threadpool(
        DeviceService().list_devices,
        workspace_id,
    )
    return _api_list(result)


@devices_router.post("/devices/pairing-code")
async def generate_device_pairing_code(workspace_id: SelectedWorkspaceIdDep) -> Any:
    result = await run_in_threadpool(
        DeviceService().generate_pairing_code,
        workspace_id,
    )
    if not result.ok or result.data is None:
        return _api_data(result)
    data = result.data
    return {
            "code": data.code,
            "expires_at": data.expires_at,
            "gateway_url": data.gateway_url,
            "qr_payload": data.qr_payload,
            "qr_svg": render_qr_svg(data.qr_payload),
        }


@devices_router.delete("/devices/{device_id}")
async def revoke_device(
    device_id: str,
    workspace_id: SelectedWorkspaceIdDep,
) -> Any:
    result = await run_in_threadpool(
        DeviceService().revoke_device,
        device_id,
        workspace_id,
    )
    return _api_data(result)
