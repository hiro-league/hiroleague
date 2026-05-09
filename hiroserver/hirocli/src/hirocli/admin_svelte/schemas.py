"""Pydantic models shared by Svelte admin HTTP routes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


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
    tts_instructions: str = ""
    tts_voice_by_provider_json: str = "{}"
    emotions_enabled: bool = False
    extras_json: str = ""


class CharacterPhotoUploadRequest(BaseModel):
    data_url: str


class ChatChannelSaveRequest(BaseModel):
    name: str
    character_id: str
    description: str = ""


class ChatChannelPhotoUploadRequest(BaseModel):
    data_url: str


class LogsTailRequest(BaseModel):
    """POST /logs/tail — live tail snapshot. ``since_seconds_ago`` is ignored when ``last_session_only``."""

    after_offsets: dict[str, int] | None = None
    lines: int | None = None
    last_session_only: bool = False
    since_seconds_ago: int | None = None


class MetricsConfigureRequest(BaseModel):
    enabled: bool | None = None
    interval: float | None = None
