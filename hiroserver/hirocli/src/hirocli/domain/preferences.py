"""Workspace preferences — single source of truth for configurable choices.

``preferences.json`` holds LLM default selections (canonical catalog ids), per-model
tuning, voice/audio, and memory settings. Provider secrets live in the credential
store (``providers.json`` + OS keyring), not here.

Storage: ``<workspace>/preferences.json`` — Pydantic model serialised to JSON.
"""

from __future__ import annotations

import logging
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


class AudioPreferences(BaseModel):
    agent_replies_in_voice: bool = False
    accept_voice_from_user: bool = True


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


@dataclass(frozen=True)
class ResolvedVoiceForSynthesis:
    """Voice selection for ``TTSService.synthesize`` (short catalog model name)."""

    model: str
    voice: str = ""
    instructions: str = ""


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
    if not spec.supports_kind(expected_kind):
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


def resolve_character_llm(
    ordered_model_ids: list[str],
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Pick the first **available** chat model from a character's ``llm_models`` list.

    Falls back to ``resolve_llm(..., "chat")`` when the list is empty or no id is usable.
    Availability matches ``resolve_llm`` (catalog + credential store).
    """
    from .available_models import AvailableModelsService
    from .model_catalog import get_model_catalog
    from .workspace import workspace_id_for_path

    if credential_store is not None:
        store = credential_store
    else:
        wid = workspace_id or workspace_id_for_path(workspace_path)
        if wid is None:
            logger.debug("resolve_character_llm: workspace path not in registry — %s", workspace_path)
            return resolve_llm(prefs, workspace_path, "chat", workspace_id=workspace_id)
        store = CredentialStore(workspace_path, wid)

    cat = get_model_catalog()
    ams = AvailableModelsService(cat, store)
    seen: set[str] = set()
    for mid in ordered_model_ids:
        if not mid or mid in seen:
            continue
        seen.add(mid)
        spec = cat.get_model(mid)
        if spec is None or spec.model_kind != "chat":
            continue
        if not ams.is_model_available(mid):
            continue
        tuning = prefs.llm.tuning.get(mid, ModelTuning())
        return ResolvedModel(
            model_id=mid,
            temperature=tuning.temperature,
            max_tokens=tuning.max_tokens,
        )
    return resolve_llm(
        prefs,
        workspace_path,
        "chat",
        workspace_id=workspace_id,
        credential_store=credential_store,
    )


def resolve_character_voice(
    ordered_voice_model_ids: list[str],
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
    tts_instructions: str = "",
    tts_voice_by_provider: dict[str, str] | None = None,
) -> ResolvedVoiceForSynthesis | None:
    """Pick the first **available** TTS model from ``voice_models``; else workspace ``default_tts``.

    Returns catalog short model id plus optional voice preset / instructions for ``TTSService``.
    Character-level ``tts_voice_by_provider`` maps catalog ``provider_id`` to one preset id per provider;
    ``tts_instructions`` is a single optional global style hint for synthesis.
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

    cat = get_model_catalog()
    ams = AvailableModelsService(cat, store)

    voice_map = dict(tts_voice_by_provider or {})
    instructions = (tts_instructions or "").strip()

    def _voice_for_provider(provider_id: str) -> str:
        raw = voice_map.get(provider_id, "")
        return str(raw).strip()

    seen: set[str] = set()
    for mid in ordered_voice_model_ids:
        if not mid or mid in seen:
            continue
        seen.add(mid)
        spec = cat.get_model(mid)
        if spec is None or not spec.supports_kind("tts"):
            continue
        if not ams.is_model_available(mid):
            continue
        short = mid.split(":", 1)[1]
        pid = spec.provider_id or ""
        voice_preset = _voice_for_provider(pid)
        return ResolvedVoiceForSynthesis(model=short, voice=voice_preset, instructions=instructions)

    tts_entry = resolve_llm(
        prefs,
        workspace_path,
        "tts",
        workspace_id=workspace_id,
        credential_store=credential_store,
    )
    if tts_entry is None:
        return None
    spec = cat.get_model(tts_entry.model_id)
    if spec is None or not spec.supports_kind("tts"):
        return None
    short = tts_entry.model_id.split(":", 1)[1]
    pid = spec.provider_id or ""
    voice_preset = _voice_for_provider(pid)
    return ResolvedVoiceForSynthesis(model=short, voice=voice_preset, instructions=instructions)
