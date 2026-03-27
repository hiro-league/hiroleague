"""Workspace preferences — single source of truth for configurable choices.

``preferences.json`` holds LLM default selections (canonical catalog ids), per-model
tuning, voice/audio, and memory settings. Provider secrets live in the credential
store (``providers.json`` + OS keyring), not here.

Storage: ``<workspace>/preferences.json`` — Pydantic model serialised to JSON.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from hiro_commons.constants.storage import PREFERENCES_FILENAME

from .credential_store import CredentialStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM selection (canonical catalog ids: ``openai:gpt-5.4``)
# ---------------------------------------------------------------------------

LLMPurpose = Literal["chat", "stt", "tts"]


class ModelTuning(BaseModel):
    """Per-model runtime overrides keyed by canonical model id."""

    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1)


class LLMPreferences(BaseModel):
    """Which catalog models to use when the workspace has credentials for them."""

    default_chat: str | None = None
    default_stt: str | None = None
    default_tts: str | None = None
    default_summarization: str | None = None
    tuning: dict[str, ModelTuning] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Audio / voice
# ---------------------------------------------------------------------------


class VoiceOption(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    provider: str
    model: str
    voice: str
    instructions: str = ""


class AudioPreferences(BaseModel):
    agent_replies_in_voice: bool = False
    accept_voice_from_user: bool = True
    selected_voice: str | None = None
    voice_options: list[VoiceOption] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Short-term memory (LangGraph + LangMem summarization)
# ---------------------------------------------------------------------------


class MemoryPreferences(BaseModel):
    """Token-bounded conversation context before the chat LLM."""

    summarization_enabled: bool = True
    max_context_tokens: int = Field(default=4096, ge=512)
    max_tokens_before_summary: int | None = Field(
        default=None,
        description="None = same as max_context_tokens",
    )
    max_summary_tokens: int = Field(default=256, ge=64)
    summarization_llm_id: str | None = Field(
        default=None,
        description="Optional canonical model id for summaries; overrides default_summarization when set.",
    )


# ---------------------------------------------------------------------------
# Top-level model
# ---------------------------------------------------------------------------


class WorkspacePreferences(BaseModel):
    """Root preferences object persisted as preferences.json."""

    version: int = 2
    llm: LLMPreferences = Field(default_factory=LLMPreferences)
    audio: AudioPreferences = Field(default_factory=AudioPreferences)
    memory: MemoryPreferences = Field(default_factory=MemoryPreferences)


# ---------------------------------------------------------------------------
# I/O — the only code that touches the file
# ---------------------------------------------------------------------------


def preferences_file(workspace_path: Path) -> Path:
    return workspace_path / PREFERENCES_FILENAME


def load_preferences(workspace_path: Path) -> WorkspacePreferences:
    f = preferences_file(workspace_path)
    if f.exists():
        return WorkspacePreferences.model_validate_json(f.read_text(encoding="utf-8"))
    return WorkspacePreferences()


def save_preferences(workspace_path: Path, prefs: WorkspacePreferences) -> None:
    workspace_path.mkdir(parents=True, exist_ok=True)
    preferences_file(workspace_path).write_text(
        prefs.model_dump_json(indent=2), encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Resolution — which canonical model id + tuning for a purpose?
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedModel:
    """Resolved chat/STT/TTS model from preferences + availability."""

    model_id: str
    temperature: float
    max_tokens: int


def resolve_llm(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    purpose: LLMPurpose = "chat",
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Return the default model for ``purpose`` if set, in catalog, and available.

    Availability requires the model's provider to be configured in the credential store.
    When ``credential_store`` is provided (e.g. AgentManager), it is reused to avoid
    repeated keyring/doc loads.
    """
    from .available_models import AvailableModelsService
    from .model_catalog import get_model_catalog
    from .workspace import workspace_id_for_path

    attr = f"default_{purpose}"
    model_id: str | None = getattr(prefs.llm, attr, None)
    if not model_id:
        return None

    cat = get_model_catalog()
    spec = cat.get_model(model_id)
    if spec is None:
        return None
    expected_kind = {"chat": "chat", "stt": "stt", "tts": "tts"}[purpose]
    if spec.model_kind != expected_kind:
        return None

    if credential_store is not None:
        store = credential_store
    else:
        wid = workspace_id or workspace_id_for_path(workspace_path)
        if wid is None:
            logger.debug("resolve_llm: workspace path not in registry — %s", workspace_path)
            return None
        store = CredentialStore(workspace_path, wid)

    ams = AvailableModelsService(cat, store)
    if not ams.is_model_available(model_id):
        return None

    tuning = prefs.llm.tuning.get(model_id, ModelTuning())
    return ResolvedModel(
        model_id=model_id,
        temperature=tuning.temperature,
        max_tokens=tuning.max_tokens,
    )


def resolve_summarization_llm(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Summarization model: memory override, then default_summarization, then chat default.

    Order matches ``MemoryPreferences.summarization_llm_id`` (per-conversation summarizer)
    overriding the LLM-section default.
    """
    from .available_models import AvailableModelsService
    from .model_catalog import get_model_catalog
    from .workspace import workspace_id_for_path

    if credential_store is not None:
        store = credential_store
    else:
        wid = workspace_id or workspace_id_for_path(workspace_path)
        if wid is None:
            return None
        store = CredentialStore(workspace_path, wid)

    ams = AvailableModelsService(get_model_catalog(), store)

    # Memory-specific id wins over llm.default_summarization, then chat default.
    candidates: list[str | None] = [
        prefs.memory.summarization_llm_id,
        prefs.llm.default_summarization,
        prefs.llm.default_chat,
    ]
    cat = get_model_catalog()
    for mid in candidates:
        if not mid:
            continue
        spec = cat.get_model(mid)
        if spec is None or spec.model_kind != "chat":
            continue
        if ams.is_model_available(mid):
            tuning = prefs.llm.tuning.get(mid, ModelTuning())
            return ResolvedModel(
                model_id=mid,
                temperature=tuning.temperature,
                max_tokens=tuning.max_tokens,
            )
    return None


def resolve_voice(prefs: WorkspacePreferences) -> VoiceOption | None:
    """Resolve the active voice option (selected_voice id > first option > None)."""
    options = prefs.audio.voice_options
    if not options:
        return None

    if prefs.audio.selected_voice:
        for opt in options:
            if opt.id == prefs.audio.selected_voice:
                return opt

    return options[0]
