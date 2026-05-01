"""FastAPI routes for the Svelte-based Hiro Admin.

Routes call existing admin services rather than duplicating business logic.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import dataclasses
import json
import platform
import tempfile
from functools import partial
from importlib import metadata
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME
from hirocli.admin.context import get_runtime_context
from hirocli.admin.features.catalog.service import CatalogBrowserService
from hirocli.admin.features.chat_channels.service import ChatChannelsService
from hirocli.admin.features.channels.service import ChannelService
from hirocli.admin.features.characters.service import CharacterService
from hirocli.admin.features.devices.service import DeviceService
from hirocli.admin.features.gateways.service import GatewayService
from hirocli.admin.features.logs.service import LogsService
from hirocli.admin.features.metrics.service import MetricsAdminService
from hirocli.admin.features.providers.service import ProvidersPageService
from hirocli.admin.features.workspaces.service import WorkspaceService
from hirocli.admin.shared.result import Result
from hirocli.domain.config import load_config, resolve_log_dir
from hirocli.domain.workspace import resolve_workspace
from hirocli.environment import get_environment_config
from hirocli.qr_rendering import render_qr_svg

api_router = APIRouter(prefix="/api", tags=["hiro-admin"])


class ApiResponse(BaseModel):
    ok: bool
    error: str | None = None
    data: Any = None


class WorkspaceListResponse(ApiResponse):
    hosting_workspace_id: str | None = None


class WorkspaceCreateRequest(BaseModel):
    name: str
    path: str | None = None


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = None
    gateway_url: str | None = None
    set_default: bool = False
    previous_display_name: str = ""


class WorkspaceRemoveRequest(BaseModel):
    purge: bool = False


class WorkspaceRestartRequest(BaseModel):
    admin: bool = False


class WorkspaceSetupRequest(BaseModel):
    gateway_url: str
    http_port: int | None = None
    skip_autostart: bool = False
    start_server: bool = False
    elevated_task: bool = False


class OpenFolderRequest(BaseModel):
    path: str


class GatewayCreateRequest(BaseModel):
    name: str
    desktop_public_key: str
    port: int
    host: str = "0.0.0.0"
    log_dir: str = ""
    make_default: bool = False
    skip_autostart: bool = False
    elevated_task: bool = False


class GatewayStartRequest(BaseModel):
    verbose: bool = False


class GatewayRemoveRequest(BaseModel):
    purge: bool = False
    elevated_task: bool = False


class ProviderAddApiKeyRequest(BaseModel):
    provider_id: str
    api_key: str


class CharacterSaveRequest(BaseModel):
    character_id: str | None = None
    name: str = ""
    description: str = ""
    prompt: str | None = None
    backstory: str = ""
    llm_models_json: str = ""
    voice_models_json: str = ""
    emotions_enabled: bool = False
    extras_json: str = ""


class CharacterPhotoUploadRequest(BaseModel):
    data_url: str


class ChatChannelSaveRequest(BaseModel):
    name: str
    user_id: int
    agent_id: str
    channel_type: str = "direct"


class LogsTailRequest(BaseModel):
    after_offsets: dict[str, int] | None = None
    lines: int | None = None


class MetricsConfigureRequest(BaseModel):
    enabled: bool | None = None
    interval: float | None = None


STATUS_STREAM_INTERVAL_SECONDS = 2.0


def _hosting_workspace_id() -> str | None:
    ctx = get_runtime_context()
    return ctx.hosting_workspace_id if ctx else None


def _selected_workspace_id(header_workspace_id: str | None) -> str | None:
    selected = (header_workspace_id or "").strip()
    return selected or _hosting_workspace_id()


def _workspace_name(workspace_id: str | None) -> str | None:
    try:
        entry, _ = resolve_workspace(workspace_id)
        return entry.name
    except Exception:
        ctx = get_runtime_context()
        return ctx.hosting_workspace_name if ctx else None


def _package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "unknown"


def _hiro_package_version() -> str:
    version = _package_version("hiroleague")
    return version if version != "unknown" else _package_version("hirocli")


def _workspace_status_label(row: dict[str, Any] | None) -> tuple[str, str]:
    if row is None or not row.get("running"):
        return "stopped", "Workspace not running"
    if not row.get("ws_connected"):
        return "running_disconnected", "Workspace running, gateway disconnected"
    return "connected", "Workspace running and connected to gateway"


def _status_snapshot(workspace_id: str | None = None) -> dict[str, Any]:
    hosting_workspace_id = _hosting_workspace_id()
    workspaces = WorkspaceService().list_rows(hosting_workspace_id)
    gateways = GatewayService().list_instances()
    workspace_rows = workspaces.data if workspaces.ok and workspaces.data is not None else []
    gateway_rows = gateways.data if gateways.ok and gateways.data is not None else []

    selected_workspace_id = workspace_id or hosting_workspace_id
    selected_row = next(
        (row for row in workspace_rows if selected_workspace_id and row.get("id") == selected_workspace_id),
        None,
    )
    if selected_row is None:
        selected_row = next((row for row in workspace_rows if row.get("is_current")), None)
    if selected_row is None and workspace_rows:
        selected_row = workspace_rows[0]

    status, status_label = _workspace_status_label(selected_row)
    return {
        "workspace": selected_row,
        "workspace_status": status,
        "workspace_status_label": status_label,
        "workspaces": workspace_rows,
        "workspaces_error": None if workspaces.ok else workspaces.error,
        "gateways": gateway_rows,
        "gateways_error": None if gateways.ok else gateways.error,
        "hosting_workspace_id": hosting_workspace_id,
    }


def _api_from_result(result: Result[Any]) -> dict[str, Any]:
    if not result.ok:
        return {"ok": False, "error": result.error or "Operation failed.", "data": None}
    return {"ok": True, "error": None, "data": result.data}


def _character_save_payload(data: Any) -> dict[str, Any]:
    return {
        "character": getattr(data, "character", {}),
        "warnings": list(getattr(data, "warnings", [])),
    }


def _decode_photo_data_url(data_url: str) -> bytes:
    if not data_url.startswith("data:"):
        raise ValueError("Photo upload must be a data URL.")
    try:
        meta, b64 = data_url.split(",", 1)
    except ValueError as exc:
        raise ValueError("Invalid photo data URL.") from exc
    if "base64" not in meta:
        raise ValueError("Photo data URL must be base64 encoded.")
    try:
        return base64.standard_b64decode(b64)
    except binascii.Error as exc:
        raise ValueError("Invalid photo image data.") from exc


def _workspace_log_dir(workspace_id: str | None):
    entry, _ = resolve_workspace(workspace_id)
    ws_path = Path(entry.path)
    config = load_config(ws_path)
    return resolve_log_dir(ws_path, config)


def _shape_log_rows(rows: list[dict[str, Any]], service: LogsService) -> list[dict[str, Any]]:
    shaped: list[dict[str, Any]] = []
    for row in rows:
        next_row = dict(row)
        message = str(next_row.get("message", "") or "")
        message_ok, message_pretty = service.pretty_print_log_field(message)
        next_row["message_pretty"] = message_pretty if message_ok else None

        segments: list[dict[str, Any]] = []
        raw_extra = str(next_row.get("extra", "") or "")
        for segment in service.split_log_extra_segments(raw_extra):
            key, value = service.log_segment_key_value(segment)
            value_ok, value_pretty = service.pretty_print_log_field(value)
            segments.append(
                {
                    "key": key or None,
                    "value": value,
                    "pretty": value_pretty if value_ok else None,
                }
            )
        next_row["extra_segments"] = segments
        shaped.append(next_row)
    return shaped


def _logs_layout(workspace_id: str | None) -> Result[dict[str, Any]]:
    service = LogsService()
    try:
        log_dir = _workspace_log_dir(workspace_id)
        gateway_log_dir = service.resolve_gateway_log_dir_fallback()
        info = service.layout_info(log_dir, gateway_log_dir)
        if not info.ok or info.data is None:
            return Result.failure(info.error or "Failed to inspect log directory.")
        return Result.success(
            {
                "available_channels": info.data.available_channels,
                "has_gateway": info.data.has_gateway,
                "has_cli": info.data.has_cli,
            }
        )
    except Exception as exc:
        return Result.failure(str(exc))


@api_router.get("/config")
async def get_admin_config(
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    config = get_environment_config()
    data = dataclasses.asdict(config)
    data.update(
        {
            "workspace_id": _selected_workspace_id(x_hiro_workspace),
            "workspace_name": _workspace_name(_selected_workspace_id(x_hiro_workspace)),
            "python_version": platform.python_version(),
            "hiro_package_version": _hiro_package_version(),
        }
    )
    return {
        "ok": True,
        "error": None,
        "data": data,
    }


@api_router.get("/events/status")
async def stream_status_events(
    request: Request,
    workspace: str | None = None,
) -> StreamingResponse:
    async def events():
        last_payload = ""
        try:
            while not await request.is_disconnected():
                snapshot = await run_in_threadpool(_status_snapshot, workspace)
                payload = json.dumps(snapshot, separators=(",", ":"))
                if payload != last_payload:
                    yield f"event: status\ndata: {payload}\n\n"
                    last_payload = payload
                else:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(STATUS_STREAM_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            # Browser tab closes and server shutdown both cancel SSE streams.
            return

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _metrics_collector() -> Any:
    from hirocli.runtime.http_server import app as http_app

    return getattr(http_app.state, "metrics_collector", None)


@api_router.get("/workspaces")
async def list_workspaces() -> dict[str, Any]:
    """Return workspace rows for the admin UI."""
    hosting_workspace_id = _hosting_workspace_id()
    result = await run_in_threadpool(WorkspaceService().list_rows, hosting_workspace_id)
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    payload["hosting_workspace_id"] = hosting_workspace_id
    return payload


@api_router.post("/workspaces")
async def create_workspace(body: WorkspaceCreateRequest) -> dict[str, Any]:
    result = await run_in_threadpool(WorkspaceService().create, body.name, body.path)
    return _api_from_result(result)


@api_router.patch("/workspaces/{workspace_id}")
async def update_workspace(workspace_id: str, body: WorkspaceUpdateRequest) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(
            WorkspaceService().update,
            workspace_id,
            name=body.name,
            gateway_url=body.gateway_url,
            set_default=body.set_default,
            previous_display_name=body.previous_display_name,
        )
    )
    return _api_from_result(result)


@api_router.delete("/workspaces/{workspace_id}")
async def remove_workspace(workspace_id: str, body: WorkspaceRemoveRequest) -> dict[str, Any]:
    result = await run_in_threadpool(
        WorkspaceService().remove,
        workspace_id,
        body.purge,
        _hosting_workspace_id(),
    )
    return _api_from_result(result)


@api_router.post("/workspaces/{workspace_id}/start")
async def start_workspace(workspace_id: str) -> dict[str, Any]:
    result = await run_in_threadpool(WorkspaceService().start, workspace_id)
    if not result.ok or result.data is None:
        return _api_from_result(result)
    name, already_running, pid = result.data
    return {
        "ok": True,
        "error": None,
        "data": {"name": name, "already_running": already_running, "pid": pid},
    }


@api_router.post("/workspaces/{workspace_id}/stop")
async def stop_workspace(workspace_id: str) -> dict[str, Any]:
    result = await run_in_threadpool(
        WorkspaceService().stop,
        workspace_id,
        _hosting_workspace_id(),
    )
    return _api_from_result(result)


@api_router.post("/workspaces/{workspace_id}/restart")
async def restart_workspace(workspace_id: str, body: WorkspaceRestartRequest) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(WorkspaceService().restart, workspace_id, admin=body.admin)
    )
    return _api_from_result(result)


@api_router.post("/workspaces/{workspace_id}/setup")
async def setup_workspace(workspace_id: str, body: WorkspaceSetupRequest) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(
            WorkspaceService().setup,
            workspace_id,
            gateway_url=body.gateway_url,
            http_port=body.http_port,
            skip_autostart=body.skip_autostart,
            start_server=body.start_server,
            elevated_task=body.elevated_task,
        )
    )
    if not result.ok or result.data is None:
        return _api_from_result(result)
    setup_result = result.data
    return {
        "ok": True,
        "error": None,
        "data": {
            "workspace": getattr(setup_result, "workspace", ""),
            "desktop_pub": getattr(setup_result, "desktop_pub", ""),
        },
    }


@api_router.get("/workspaces/{workspace_id}/public-key")
async def get_workspace_public_key(workspace_id: str) -> dict[str, Any]:
    result = await run_in_threadpool(WorkspaceService().get_public_key, workspace_id)
    return _api_from_result(result)


@api_router.post("/workspaces/{workspace_id}/regenerate-key")
async def regenerate_workspace_key(workspace_id: str) -> dict[str, Any]:
    result = await run_in_threadpool(WorkspaceService().regenerate_key, workspace_id)
    return _api_from_result(result)


@api_router.post("/workspaces/open-folder")
async def open_workspace_folder(body: OpenFolderRequest) -> dict[str, Any]:
    result = await run_in_threadpool(WorkspaceService().open_folder, body.path)
    return _api_from_result(result)


@api_router.post("/open-path")
async def open_path(body: OpenFolderRequest) -> dict[str, Any]:
    result = await run_in_threadpool(WorkspaceService().open_folder, body.path)
    return _api_from_result(result)


@api_router.get("/gateways")
async def list_gateways() -> dict[str, Any]:
    result = await run_in_threadpool(GatewayService().list_instances)
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    return payload


@api_router.get("/catalog/providers")
async def list_catalog_providers(hosting: str | None = None) -> dict[str, Any]:
    result = await run_in_threadpool(CatalogBrowserService().list_providers, hosting)
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    return payload


@api_router.get("/catalog/models")
async def list_catalog_models(
    provider_id: str | None = None,
    model_kind: str | None = None,
    model_class: str | None = None,
    hosting: str | None = None,
) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(
            CatalogBrowserService().list_models,
            provider_id=provider_id,
            model_kind=model_kind,
            model_class=model_class,
            hosting=hosting,
        )
    )
    if not result.ok or result.data is None:
        return _api_from_result(result)
    catalog_version, models = result.data
    return {
        "ok": True,
        "error": None,
        "data": {"catalog_version": catalog_version, "models": models},
    }


@api_router.get("/providers")
async def list_active_providers(
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().list_configured,
        _selected_workspace_id(x_hiro_workspace),
    )
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    return payload


@api_router.get("/providers/addable")
async def list_addable_providers(
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().list_addable_cloud_providers,
        _selected_workspace_id(x_hiro_workspace),
    )
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    return payload


@api_router.post("/providers")
async def add_provider_api_key(
    body: ProviderAddApiKeyRequest,
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().add_api_key,
        _selected_workspace_id(x_hiro_workspace),
        body.provider_id,
        body.api_key,
    )
    return _api_from_result(result)


@api_router.post("/providers/scan-env")
async def scan_provider_environment(
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().scan_environment_for_keys,
        _selected_workspace_id(x_hiro_workspace),
    )
    return _api_from_result(result)


@api_router.delete("/providers/{provider_id}")
async def remove_provider(
    provider_id: str,
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ProvidersPageService().remove_provider,
        _selected_workspace_id(x_hiro_workspace),
        provider_id,
    )
    return _api_from_result(result)


@api_router.get("/characters")
async def list_characters(
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        CharacterService().list_characters_with_preview_images,
        _selected_workspace_id(x_hiro_workspace),
    )
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    return payload


@api_router.post("/characters")
async def create_character(
    body: CharacterSaveRequest,
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(
            CharacterService().create_character,
            _selected_workspace_id(x_hiro_workspace),
            character_id=body.character_id or "",
            name=body.name,
            description=body.description,
            prompt=body.prompt,
            backstory=body.backstory,
            llm_models_json=body.llm_models_json,
            voice_models_json=body.voice_models_json,
            emotions_enabled=body.emotions_enabled,
            extras_json=body.extras_json,
        )
    )
    if not result.ok or result.data is None:
        return _api_from_result(result)
    return {"ok": True, "error": None, "data": _character_save_payload(result.data)}


@api_router.get("/characters/{character_id}")
async def get_character(
    character_id: str,
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    workspace_id = _selected_workspace_id(x_hiro_workspace)
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


@api_router.patch("/characters/{character_id}")
async def update_character(
    character_id: str,
    body: CharacterSaveRequest,
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(
            CharacterService().update_character,
            _selected_workspace_id(x_hiro_workspace),
            character_id,
            name=body.name,
            description=body.description,
            prompt=body.prompt,
            backstory=body.backstory,
            llm_models_json=body.llm_models_json,
            voice_models_json=body.voice_models_json,
            emotions_enabled=body.emotions_enabled,
            extras_json=body.extras_json,
        )
    )
    if not result.ok or result.data is None:
        return _api_from_result(result)
    return {"ok": True, "error": None, "data": _character_save_payload(result.data)}


@api_router.delete("/characters/{character_id}")
async def delete_character(
    character_id: str,
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        CharacterService().delete_character,
        _selected_workspace_id(x_hiro_workspace),
        character_id,
    )
    return _api_from_result(result)


@api_router.post("/characters/{character_id}/photo")
async def upload_character_photo(
    character_id: str,
    body: CharacterPhotoUploadRequest,
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        raw = _decode_photo_data_url(body.data_url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "data": None}
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    try:
        result = await run_in_threadpool(
            CharacterService().upload_photo,
            _selected_workspace_id(x_hiro_workspace),
            character_id,
            tmp_path,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return _api_from_result(result)


@api_router.get("/channels")
async def list_channels(
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ChannelService().list_channels,
        _selected_workspace_id(x_hiro_workspace),
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


@api_router.post("/channels/{channel_name}/enable")
async def enable_channel(
    channel_name: str,
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ChannelService().enable_channel,
        channel_name,
        _selected_workspace_id(x_hiro_workspace),
    )
    return _api_from_result(result)


@api_router.post("/channels/{channel_name}/disable")
async def disable_channel(
    channel_name: str,
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ChannelService().disable_channel,
        channel_name,
        _selected_workspace_id(x_hiro_workspace),
    )
    return _api_from_result(result)


@api_router.get("/chat-channels")
async def list_chat_channels(
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ChatChannelsService().list_channels,
        _selected_workspace_id(x_hiro_workspace),
    )
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    return payload


@api_router.post("/chat-channels")
async def create_chat_channel(
    body: ChatChannelSaveRequest,
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(
            ChatChannelsService().create_channel,
            _selected_workspace_id(x_hiro_workspace),
            name=body.name,
            user_id=body.user_id,
            agent_id=body.agent_id,
            channel_type=body.channel_type,
        )
    )
    return _api_from_result(result)


@api_router.patch("/chat-channels/{channel_id}")
async def update_chat_channel(
    channel_id: int,
    body: ChatChannelSaveRequest,
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        partial(
            ChatChannelsService().update_channel,
            _selected_workspace_id(x_hiro_workspace),
            channel_id,
            name=body.name,
            channel_type=body.channel_type,
            agent_id=body.agent_id,
            user_id=body.user_id,
        )
    )
    return _api_from_result(result)


@api_router.delete("/chat-channels/{channel_id}")
async def delete_chat_channel(
    channel_id: int,
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ChatChannelsService().delete_channel,
        _selected_workspace_id(x_hiro_workspace),
        channel_id,
    )
    return _api_from_result(result)


@api_router.get("/chat-channels/{channel_id}/messages")
async def list_chat_channel_messages(
    channel_id: int,
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        ChatChannelsService().list_messages_all,
        _selected_workspace_id(x_hiro_workspace),
        channel_id,
    )
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    return payload


@api_router.get("/devices")
async def list_devices(
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        DeviceService().list_devices,
        _selected_workspace_id(x_hiro_workspace),
    )
    payload = _api_from_result(result)
    payload["data"] = payload["data"] or []
    return payload


@api_router.post("/devices/pairing-code")
async def generate_device_pairing_code(
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        DeviceService().generate_pairing_code,
        _selected_workspace_id(x_hiro_workspace),
    )
    if not result.ok or result.data is None:
        return _api_from_result(result)
    data = result.data
    return {
        "ok": True,
        "error": None,
        "data": {
            "code": data.code,
            "expires_at": data.expires_at,
            "gateway_url": data.gateway_url,
            "qr_payload": data.qr_payload,
            "qr_svg": render_qr_svg(data.qr_payload),
        },
    }


@api_router.delete("/devices/{device_id}")
async def revoke_device(
    device_id: str,
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(
        DeviceService().revoke_device,
        device_id,
        _selected_workspace_id(x_hiro_workspace),
    )
    return _api_from_result(result)


@api_router.get("/logs/layout")
async def get_logs_layout(
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    result = await run_in_threadpool(_logs_layout, _selected_workspace_id(x_hiro_workspace))
    return _api_from_result(result)


@api_router.post("/logs/tail")
async def tail_logs(
    body: LogsTailRequest,
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    service = LogsService()
    workspace_id = _selected_workspace_id(x_hiro_workspace)
    if body.after_offsets:
        result = await run_in_threadpool(
            service.tail_after_offsets,
            workspace_id,
            body.after_offsets,
        )
    else:
        result = await run_in_threadpool(
            partial(service.tail_initial, workspace_id, lines=body.lines or 500)
        )
    if not result.ok or result.data is None:
        return _api_from_result(result)
    return {
        "ok": True,
        "error": None,
        "data": {
            "rows": _shape_log_rows(result.data.rows, service),
            "file_offsets": result.data.file_offsets,
        },
    }


@api_router.get("/logs/search")
async def search_logs(
    query: str,
    x_hiro_workspace: str | None = Header(default=None),
) -> dict[str, Any]:
    service = LogsService()
    result = await run_in_threadpool(
        service.search,
        _selected_workspace_id(x_hiro_workspace),
        query,
    )
    if not result.ok:
        return _api_from_result(result)
    return {
        "ok": True,
        "error": None,
        "data": {"rows": _shape_log_rows(result.data or [], service)},
    }


@api_router.get("/metrics/tick")
async def metrics_tick() -> dict[str, Any]:
    collector = _metrics_collector()
    if collector is None:
        return {
            "ok": True,
            "error": None,
            "data": {
                "available": False,
                "enabled": False,
                "interval": 2.0,
                "status_text": "Metrics collector is not available.",
                "frame": None,
            },
        }

    payload = MetricsAdminService().prepare_tick(collector)
    frame = dataclasses.asdict(payload.frame) if payload.frame is not None else None
    return {
        "ok": True,
        "error": None,
        "data": {
            "available": True,
            "enabled": collector.enabled,
            "interval": collector.interval,
            "status_text": payload.status_text,
            "frame": frame,
        },
    }


@api_router.post("/metrics/configure")
async def configure_metrics_for_admin(body: MetricsConfigureRequest) -> dict[str, Any]:
    collector = _metrics_collector()
    if collector is None:
        return {"ok": False, "error": "Metrics collector is not available.", "data": None}
    result = MetricsAdminService().configure(
        collector,
        enabled=body.enabled,
        interval=body.interval,
    )
    return _api_from_result(result)


@api_router.post("/gateways")
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


@api_router.post("/gateways/{instance_name}/start")
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


@api_router.post("/gateways/{instance_name}/stop")
async def stop_gateway(instance_name: str) -> dict[str, Any]:
    result = await run_in_threadpool(GatewayService().stop, instance_name)
    return _api_from_result(result)


@api_router.delete("/gateways/{instance_name}")
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


def include_admin_svelte_api(app: Any) -> None:
    """Attach Svelte admin API routes to the admin FastAPI app."""
    app.include_router(api_router)
