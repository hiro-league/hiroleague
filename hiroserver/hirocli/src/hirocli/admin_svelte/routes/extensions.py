"""Extension routes: the paired list with live status, pairing codes, removal,
the listen address, and the core's test call to an extension.

Live state comes from the running server's ExtensionManager (``ctx.extension_manager``)
and applies only when the selected workspace is the one this server runs.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from hiro_channel_sdk.constants import METHOD_EXTENSION_INFO
from hiro_channel_sdk.extension import ExtensionRequestError

from hirocli.admin.features.extensions.service import ExtensionService
from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import _api_from_result, envelope_failure

extensions_router = APIRouter()


class AddressBody(BaseModel):
    host: str


def _live_manager(request: Request, workspace_path: Path | None) -> Any:
    """The running ExtensionManager when it serves the selected workspace, else None."""
    ctx = getattr(request.app.state, "ctx", None)
    manager = getattr(ctx, "extension_manager", None) if ctx is not None else None
    if manager is None or workspace_path is None:
        return None
    try:
        same = Path(ctx.workspace_path).resolve() == workspace_path.resolve()
    except OSError:
        same = False
    return manager if same else None


@extensions_router.get("/extensions")
async def list_extensions(request: Request, workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    service = ExtensionService()
    listed = await run_in_threadpool(service.list_extensions, workspace_id)
    if not listed.ok:
        return _api_from_result(listed)
    address = await run_in_threadpool(service.address, workspace_id)
    workspace_path = await run_in_threadpool(service.workspace_path, workspace_id)
    manager = _live_manager(request, workspace_path)
    live = manager.snapshot() if manager is not None else {}
    extensions = []
    for ext in listed.data or []:
        conn = live.get(ext["extension_id"])
        extensions.append(
            {
                **ext,
                "connected": conn is not None,
                "connected_at": conn["connected_at"] if conn else None,
                "remote": conn["remote"] if conn else None,
                # The live connection knows the current version; the table the last one.
                "version": (conn["info"].get("version") if conn else None) or ext["version"],
            }
        )
    listen = asdict(address.data) if address.ok and address.data is not None else {}
    if manager is not None:
        state = manager.listen_state()
        # What the server is actually doing, which can differ from config until a restart.
        listen.update({"listening": state["listening"], "error": state["error"], "live_host": state["host"]})
    else:
        listen.update({"listening": None, "error": None, "live_host": None})
    return {"ok": True, "error": None, "data": {"listen": listen, "extensions": extensions}}


@extensions_router.post("/extensions/pairing-code")
async def generate_extension_pairing_code(workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    result = await run_in_threadpool(ExtensionService().generate_pairing_code, workspace_id)
    if not result.ok or result.data is None:
        return _api_from_result(result)
    return {"ok": True, "error": None, "data": asdict(result.data)}


@extensions_router.delete("/extensions/{extension_id}")
async def remove_extension(
    extension_id: str, request: Request, workspace_id: SelectedWorkspaceIdDep
) -> dict[str, Any]:
    service = ExtensionService()
    result = await run_in_threadpool(service.remove_extension, extension_id, workspace_id)
    if result.ok:
        workspace_path = await run_in_threadpool(service.workspace_path, workspace_id)
        manager = _live_manager(request, workspace_path)
        if manager is not None:
            # Close it now; it is refused when it tries again.
            await manager.disconnect(extension_id)
    return _api_from_result(result)


@extensions_router.put("/extensions/address")
async def set_extension_address(body: AddressBody, workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    result = await run_in_threadpool(ExtensionService().address, workspace_id, body.host)
    if not result.ok or result.data is None:
        return _api_from_result(result)
    return {"ok": True, "error": None, "data": asdict(result.data)}


@extensions_router.post("/extensions/{extension_id}/info")
async def ask_extension_info(
    extension_id: str, request: Request, workspace_id: SelectedWorkspaceIdDep
) -> dict[str, Any]:
    """The core's test call: ask a connected extension for its name and version."""
    workspace_path = await run_in_threadpool(ExtensionService().workspace_path, workspace_id)
    manager = _live_manager(request, workspace_path)
    if manager is None:
        return envelope_failure("The server for this workspace isn't running here.")
    started = time.perf_counter()
    try:
        data = await manager.request(extension_id, METHOD_EXTENSION_INFO)
    except ExtensionRequestError as exc:
        return envelope_failure(exc.message)
    return {
        "ok": True,
        "error": None,
        "data": {"info": data, "elapsed_ms": round((time.perf_counter() - started) * 1000)},
    }
