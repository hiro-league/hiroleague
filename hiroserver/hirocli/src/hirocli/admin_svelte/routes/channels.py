"""Generic channel-plugin admin routes (design §5.3).

One parameterized surface for every channel (WhatsApp today, Telegram/… next):
list, live status, pairing, config get/set, install, enable/disable (with live
hot spawn/stop), and generic actions. The channel declares its config schema and
capabilities at registration (§5.1/§5.2); these routes stay channel-agnostic and
read that descriptor instead of hardcoding per-channel behavior.

Config writes and status/pairing reads go through the shared ServerContext
(``channel_status`` cache written by InfraEventHandlers, ``channel_manager`` for
live actions). All endpoints return the ``{ok, error, data}`` envelope.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME
from hirocli.admin.features.channels.service import ChannelService
from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import _api_from_result, envelope_failure
from hirocli.domain.channel_config import load_channel_config
from hirocli.domain.channel_descriptor import load_channel_descriptor
from hirocli.qr_rendering import render_qr_svg
from hirocli.tools.channel import (
    ChannelConfigSetTool,
    ChannelConfigShowTool,
    ChannelDisableTool,
    ChannelEnableTool,
    ChannelInstallTool,
)

channels_router = APIRouter()


def _ctx(request: Request) -> Any:
    return getattr(request.app.state, "ctx", None)


def _channel_manager(request: Request) -> Any:
    ctx = _ctx(request)
    return getattr(ctx, "channel_manager", None) if ctx is not None else None


def _status_for(request: Request, name: str) -> dict[str, Any] | None:
    ctx = _ctx(request)
    if ctx is None:
        return None
    return dict(getattr(ctx, "channel_status", {}).get(name, {}))


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

@channels_router.get("/channels")
async def list_channels(workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    result = await run_in_threadpool(ChannelService().list_channels, workspace_id)
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


# ---------------------------------------------------------------------------
# Live status / pairing / descriptor
# ---------------------------------------------------------------------------

@channels_router.get("/channels/{name}/status")
async def channel_status(name: str, request: Request) -> dict[str, Any]:
    ctx = _ctx(request)
    if ctx is None:
        return envelope_failure("Admin app has no ServerContext attached.")
    st = dict(getattr(ctx, "channel_status", {}).get(name, {}))
    cfg = await run_in_threadpool(load_channel_config, ctx.workspace_path, name)
    descriptor = await run_in_threadpool(load_channel_descriptor, ctx.workspace_path, name)
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
            # §5.2 — capability descriptor drives the pairing pane / action buttons.
            "capabilities": descriptor.capabilities if descriptor is not None else None,
        },
    }


@channels_router.get("/channels/{name}/pairing")
async def channel_pairing(name: str, request: Request) -> dict[str, Any]:
    st = _status_for(request, name)
    if st is None:
        return envelope_failure("Admin app has no ServerContext attached.")
    # Render the raw pairing string to an SVG server-side (same helper the device
    # pairing dialog uses); token/oauth channels carry no code and render nothing.
    raw = st.get("qr", "")
    qr_svg = render_qr_svg(raw) if raw else ""
    return {
        "ok": True,
        "error": None,
        "data": {"kind": st.get("pairing_kind", "qr"), "qr_svg": qr_svg, "qr_at": st.get("qr_at")},
    }


@channels_router.get("/channels/{name}/descriptor")
async def channel_descriptor(name: str, request: Request) -> dict[str, Any]:
    ctx = _ctx(request)
    if ctx is None:
        return envelope_failure("Admin app has no ServerContext attached.")
    d = await run_in_threadpool(load_channel_descriptor, ctx.workspace_path, name)
    if d is None:
        # Channel never registered → no declared schema/capabilities yet.
        return {"ok": True, "error": None, "data": {"config_schema": None, "capabilities": None, "version": ""}}
    return {
        "ok": True,
        "error": None,
        "data": {"config_schema": d.config_schema, "capabilities": d.capabilities, "version": d.version},
    }


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@channels_router.get("/channels/{name}/config")
async def channel_config_show(name: str, workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    try:
        result = await run_in_threadpool(ChannelConfigShowTool().execute, name, workspace_id)
    except ValueError as exc:
        return envelope_failure(str(exc))
    return {"ok": True, "error": None, "data": {"config": result.config}}


class ConfigSetRequest(BaseModel):
    key: str
    value: Any | None = None  # None ⇒ unset the key


@channels_router.post("/channels/{name}/config")
async def channel_config_set(
    name: str, body: ConfigSetRequest, workspace_id: SelectedWorkspaceIdDep
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
            ChannelConfigSetTool().execute, name, body.key, raw, workspace_id
        )
    except (ValueError, RuntimeError) as exc:
        # ValueError: schema-validation failures (unknown key / wrong type, §5.1) or a
        # secret write on a non-registry workspace. RuntimeError: keyring unavailable (§5.6).
        return envelope_failure(str(exc))
    return {"ok": True, "error": None, "data": {"config": result.config}}


# ---------------------------------------------------------------------------
# Install / lifecycle / actions
# ---------------------------------------------------------------------------

class InstallRequest(BaseModel):
    package: str | None = None
    editable: bool = False


@channels_router.post("/channels/{name}/install")
async def channel_install(name: str, body: InstallRequest) -> dict[str, Any]:
    try:
        result = await run_in_threadpool(
            ChannelInstallTool().execute, name, body.package, body.editable
        )
    except RuntimeError as exc:
        return envelope_failure(str(exc))
    return {"ok": True, "error": None, "data": {"package": result.package, "output": result.output}}


@channels_router.post("/channels/{name}/enable")
async def enable_channel(
    name: str, request: Request, workspace_id: SelectedWorkspaceIdDep
) -> dict[str, Any]:
    # Persist enabled=True (survives restart), then hot-spawn the plugin live (§5.5).
    try:
        await run_in_threadpool(ChannelEnableTool().execute, name, workspace_id)
    except (ValueError, RuntimeError) as exc:
        return envelope_failure(str(exc))
    cm = _channel_manager(request)
    if cm is not None:
        await cm.activate(name)
    return {"ok": True, "error": None, "data": {"enabled": True}}


@channels_router.post("/channels/{name}/disable")
async def disable_channel(
    name: str, request: Request, workspace_id: SelectedWorkspaceIdDep
) -> dict[str, Any]:
    # Persist enabled=False, then stop the running plugin live.
    try:
        await run_in_threadpool(ChannelDisableTool().execute, name, workspace_id)
    except (ValueError, RuntimeError) as exc:
        return envelope_failure(str(exc))
    cm = _channel_manager(request)
    if cm is not None:
        await cm.deactivate(name)
    ctx = _ctx(request)
    if ctx is not None:
        ctx.channel_status.setdefault(name, {})["state"] = "disabled"
    return {"ok": True, "error": None, "data": {"enabled": False}}


@channels_router.post("/channels/{name}/action/{action}")
async def channel_action(name: str, action: str, request: Request) -> dict[str, Any]:
    # Generic admin action (§5.2/§5.4): forwarded to the plugin as a channel.<action>
    # event (e.g. logout, reconnect). Rejected if the channel declares an action set
    # that doesn't include it.
    cm = _channel_manager(request)
    if cm is None:
        return envelope_failure("Channel manager not available (is the server running?).")
    ctx = _ctx(request)
    if ctx is not None:
        d = await run_in_threadpool(load_channel_descriptor, ctx.workspace_path, name)
        declared = (d.capabilities or {}).get("actions") if d is not None and d.capabilities else None
        if declared is not None and action not in declared:
            return envelope_failure(f"Channel '{name}' does not support action '{action}'.")
    await cm.send_event_to_channel(name, f"channel.{action}", {})
    return {"ok": True, "error": None, "data": {"requested": True, "action": action}}
