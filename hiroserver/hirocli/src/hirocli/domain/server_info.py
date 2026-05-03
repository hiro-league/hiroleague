from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, Field

from .character import default_character_id, load_character_from_disk
from .conversation_channel import _list_channels
from .credential_store import CredentialStore
from .preferences import (
    MediaPreferences,
    ModalityFlags,
    WorkspacePreferences,
    load_preferences,
    resolve_character_voice,
    resolve_llm,
)
from .workspace import workspace_id_for_path

logger = logging.getLogger(__name__)


class ServerInfoCharacter(BaseModel):
    id: str
    name: str


class ServerInfoChannel(BaseModel):
    id: int
    name: str
    character: ServerInfoCharacter
    capabilities: MediaPreferences


class ServerInfoSnapshot(BaseModel):
    version: int = 1
    policy: MediaPreferences
    channels: list[ServerInfoChannel] = Field(default_factory=list)


def _load_character_for_channel(workspace_path: Path, character_id: str):
    resolved_character_id = (character_id or "").strip()
    if not resolved_character_id:
        resolved_character_id = default_character_id(workspace_path)
    try:
        return load_character_from_disk(workspace_path, resolved_character_id)
    except FileNotFoundError:
        fallback_character_id = default_character_id(workspace_path)
        return load_character_from_disk(workspace_path, fallback_character_id)


def resolve_modality_capability(
    modality: str,
    direction: str,
    *,
    prefs: WorkspacePreferences,
    workspace_path: Path,
    character,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> bool:
    if modality != "voice":
        return False

    if direction == "input":
        if not prefs.media.input.voice:
            return False
        return (
            resolve_llm(
                prefs,
                workspace_path,
                "stt",
                workspace_id=workspace_id,
                credential_store=credential_store,
            )
            is not None
        )

    if direction == "output":
        if not prefs.media.output.voice or character is None:
            return False
        return (
            resolve_character_voice(
                character.voice_models,
                prefs,
                workspace_path,
                workspace_id=workspace_id,
                credential_store=credential_store,
                tts_instructions=character.tts_instructions,
                tts_voice_by_provider=dict(character.tts_voice_by_provider),
            )
            is not None
        )

    raise ValueError(f"Unsupported direction: {direction}")


def _resolve_direction_flags(
    direction: str,
    *,
    prefs: WorkspacePreferences,
    workspace_path: Path,
    character,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ModalityFlags:
    return ModalityFlags(
        voice=resolve_modality_capability(
            "voice",
            direction,
            prefs=prefs,
            workspace_path=workspace_path,
            character=character,
            workspace_id=workspace_id,
            credential_store=credential_store,
        ),
        image=False,
        video=False,
        file=False,
    )


def resolve_channel_capabilities(
    workspace_path: Path,
    *,
    prefs: WorkspacePreferences,
    character,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> MediaPreferences:
    return MediaPreferences(
        input=_resolve_direction_flags(
            "input",
            prefs=prefs,
            workspace_path=workspace_path,
            character=character,
            workspace_id=workspace_id,
            credential_store=credential_store,
        ),
        output=_resolve_direction_flags(
            "output",
            prefs=prefs,
            workspace_path=workspace_path,
            character=character,
            workspace_id=workspace_id,
            credential_store=credential_store,
        ),
    )


def build_server_info_snapshot(
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ServerInfoSnapshot:
    prefs = load_preferences(workspace_path)
    resolved_workspace_id = workspace_id or workspace_id_for_path(workspace_path)
    channels: list[ServerInfoChannel] = []

    for channel in _list_channels(workspace_path):
        character = _load_character_for_channel(workspace_path, channel.character_id)
        channels.append(
            ServerInfoChannel(
                id=channel.id,
                name=channel.name,
                character=ServerInfoCharacter(id=character.id, name=character.name),
                capabilities=resolve_channel_capabilities(
                    workspace_path,
                    prefs=prefs,
                    character=character,
                    workspace_id=resolved_workspace_id,
                    credential_store=credential_store,
                ),
            )
        )

    snapshot = ServerInfoSnapshot(
        # Keep the saved policy untouched; channels carry the effective values.
        policy=prefs.media.model_copy(deep=True),
        channels=channels,
    )
    logger.debug(
        "Built server info snapshot",
        extra={"workspace_path": str(workspace_path), "channels": len(channels)},
    )
    return snapshot
