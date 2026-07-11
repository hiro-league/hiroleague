"""Admin API routes for the WhatsApp channel.

Reuses the channel Tools (config get/set, install) and reads live QR / connection
status from the shared ServerContext cache (written by InfraEventHandlers on the
plugin's ``whatsapp.qr`` / ``whatsapp.status`` events). The frontend polls
``/whatsapp/qr`` + ``/whatsapp/status`` during pairing.

Gated behind the ``whatsapp`` feature (see admin_svelte/api.py).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import envelope_failure
from hirocli.domain.channel_config import load_channel_config
from hirocli.qr_rendering import render_qr_svg
from hirocli.tools.channel import (
    ChannelConfigSetTool,
    ChannelConfigShowTool,
    ChannelDisableTool,
    ChannelEnableTool,
    ChannelInstallTool,
)

_WHATSAPP = "whatsapp"

whatsapp_router = APIRouter()


def _ctx(request: Request) -> Any:
    return getattr(request.app.state, "ctx", None)


def _channel_manager(request: Request) -> Any:
    ctx = _ctx(request)
    return getattr(ctx, "channel_manager", None) if ctx is not None else None


def _status_for(request: Request) -> dict[str, Any] | None:
    ctx = _ctx(request)
    if ctx is None:
        return None
    return dict(getattr(ctx, "channel_status", {}).get(_WHATSAPP, {}))


@whatsapp_router.get("/whatsapp/status")
async def whatsapp_status(request: Request) -> dict[str, Any]:
    ctx = _ctx(request)
    if ctx is None:
        return envelope_failure("Admin app has no ServerContext attached.")
    st = dict(getattr(ctx, "channel_status", {}).get(_WHATSAPP, {}))
    cfg = await run_in_threadpool(load_channel_config, ctx.workspace_path, _WHATSAPP)
    return {
        "ok": True,
        "error": None,
        "data": {
            "state": st.get("state", "unknown"),
            "account": st.get("account", ""),
            "has_qr": bool(st.get("qr")),
            "enabled": bool(cfg.enabled) if cfg is not None else False,
            "state_at": st.get("state_at"),
            # Diagnostic detail for terminal states (reason/code/expire/message).
            "detail": st.get("detail", {}),
        },
    }


@whatsapp_router.get("/whatsapp/qr")
async def whatsapp_qr(request: Request) -> dict[str, Any]:
    st = _status_for(request)
    if st is None:
        return envelope_failure("Admin app has no ServerContext attached.")
    # Render the raw pairing string to an SVG server-side (same helper the device
    # pairing dialog uses), so the frontend just sanitizes + injects it.
    raw = st.get("qr", "")
    qr_svg = render_qr_svg(raw) if raw else ""
    return {"ok": True, "error": None, "data": {"qr_svg": qr_svg, "qr_at": st.get("qr_at")}}


@whatsapp_router.get("/whatsapp/config")
async def whatsapp_config_show(workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    try:
        result = await run_in_threadpool(ChannelConfigShowTool().execute, _WHATSAPP, workspace_id)
    except ValueError as exc:
        return envelope_failure(str(exc))
    return {"ok": True, "error": None, "data": {"config": result.config}}


class ConfigSetRequest(BaseModel):
    key: str
    value: Any | None = None  # None ⇒ unset the key


@whatsapp_router.post("/whatsapp/config")
async def whatsapp_config_set(
    body: ConfigSetRequest, workspace_id: SelectedWorkspaceIdDep
) -> dict[str, Any]:
    # The Tool takes a string and JSON-parses it; serialize non-string values so
    # lists/bools round-trip (a plain string is passed through as-is).
    if body.value is None:
        raw: str | None = None
    elif isinstance(body.value, str):
        raw = body.value
    else:
        raw = json.dumps(body.value)
    try:
        result = await run_in_threadpool(
            ChannelConfigSetTool().execute, _WHATSAPP, body.key, raw, workspace_id
        )
    except ValueError as exc:
        return envelope_failure(str(exc))
    return {"ok": True, "error": None, "data": {"config": result.config}}


class InstallRequest(BaseModel):
    package: str | None = None
    editable: bool = False


@whatsapp_router.post("/whatsapp/install")
async def whatsapp_install(body: InstallRequest) -> dict[str, Any]:
    try:
        result = await run_in_threadpool(
            ChannelInstallTool().execute, _WHATSAPP, body.package, body.editable
        )
    except RuntimeError as exc:
        return envelope_failure(str(exc))
    return {"ok": True, "error": None, "data": {"package": result.package, "output": result.output}}


@whatsapp_router.post("/whatsapp/enable")
async def whatsapp_enable(request: Request, workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    # Persist enabled=True (survives restart), then spawn the plugin live.
    try:
        await run_in_threadpool(ChannelEnableTool().execute, _WHATSAPP, workspace_id)
    except (ValueError, RuntimeError) as exc:
        return envelope_failure(str(exc))
    cm = _channel_manager(request)
    if cm is not None:
        await cm.activate(_WHATSAPP)
    return {"ok": True, "error": None, "data": {"enabled": True}}


@whatsapp_router.post("/whatsapp/disable")
async def whatsapp_disable(request: Request, workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    # Persist enabled=False, then stop the running plugin live.
    try:
        await run_in_threadpool(ChannelDisableTool().execute, _WHATSAPP, workspace_id)
    except (ValueError, RuntimeError) as exc:
        return envelope_failure(str(exc))
    cm = _channel_manager(request)
    if cm is not None:
        await cm.deactivate(_WHATSAPP)
    ctx = _ctx(request)
    if ctx is not None:
        ctx.channel_status.setdefault(_WHATSAPP, {})["state"] = "disabled"
    return {"ok": True, "error": None, "data": {"enabled": False}}


@whatsapp_router.post("/whatsapp/logout")
async def whatsapp_logout(request: Request) -> dict[str, Any]:
    # Unlink the account → the plugin clears its session and issues a fresh QR.
    cm = _channel_manager(request)
    if cm is None:
        return envelope_failure("Channel manager not available (is the server running?).")
    await cm.send_event_to_channel(_WHATSAPP, "whatsapp.logout", {})
    return {"ok": True, "error": None, "data": {"requested": True}}


@whatsapp_router.post("/whatsapp/reconnect")
async def whatsapp_reconnect(request: Request) -> dict[str, Any]:
    # Force a re-link using the saved session (no new QR).
    cm = _channel_manager(request)
    if cm is None:
        return envelope_failure("Channel manager not available (is the server running?).")
    await cm.send_event_to_channel(_WHATSAPP, "whatsapp.reconnect", {})
    return {"ok": True, "error": None, "data": {"requested": True}}
