"""Gateway instance admin routes."""

from __future__ import annotations

from functools import partial
from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from hirocli.admin.features.gateways.service import GatewayService
from hirocli.admin_svelte.result_payload import _api_from_result
from hirocli.admin_svelte.schemas import GatewayCreateRequest, GatewayRemoveRequest, GatewayStartRequest

gateways_router = APIRouter()


@gateways_router.get("/gateways")
async def list_gateways() -> dict[str, Any]:
    result = await run_in_threadpool(GatewayService().list_instances)
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    return payload


@gateways_router.post("/gateways")
async def create_gateway(body: GatewayCreateRequest) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(
            GatewayService().setup_instance,
            name=body.name,
            desktop_public_key=body.desktop_public_key,
            port=body.port,
            host=body.host,
            log_dir=body.log_dir,
            make_default=body.make_default,
            skip_autostart=body.skip_autostart,
            elevated_task=body.elevated_task,
        )
    )
    return _api_from_result(result)


@gateways_router.post("/gateways/{instance_name}/start")
async def start_gateway(instance_name: str, body: GatewayStartRequest) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(GatewayService().start, instance_name, verbose=body.verbose)
    )
    if not result.ok or result.data is None:
        return _api_from_result(result)
    already_running, pid = result.data
    return {
        "ok": True,
        "error": None,
        "data": {"already_running": already_running, "pid": pid},
    }


@gateways_router.post("/gateways/{instance_name}/stop")
async def stop_gateway(instance_name: str) -> dict[str, Any]:
    result = await run_in_threadpool(GatewayService().stop, instance_name)
    return _api_from_result(result)


@gateways_router.delete("/gateways/{instance_name}")
async def remove_gateway(instance_name: str, body: GatewayRemoveRequest) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(
            GatewayService().teardown_instance,
            instance_name,
            purge=body.purge,
            elevated_task=body.elevated_task,
        )
    )
    return _api_from_result(result)
