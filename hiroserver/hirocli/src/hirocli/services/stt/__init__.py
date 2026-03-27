"""Speech-to-text provider package.

Public API
----------
    STTProvider     — ABC for all STT providers
    ModelInfo       — dataclass describing a single model
    STTService      — orchestrator that aggregates providers and routes by model ID
    OpenAISTTProvider — OpenAI gpt-4o-transcribe family
    GeminiSTTProvider — Google Gemini multimodal transcription
    create_stt_service — factory that builds an STTService from workspace preferences
"""

from __future__ import annotations

from pathlib import Path

from hiro_commons.log import Logger

from .gemini_provider import GeminiSTTProvider
from .openai_provider import OpenAISTTProvider
from .provider import ModelInfo, STTProvider
from .service import STTService

__all__ = [
    "STTProvider",
    "ModelInfo",
    "STTService",
    "OpenAISTTProvider",
    "GeminiSTTProvider",
    "create_stt_service",
]

_log = Logger.get("STT")

# Catalog provider_id → STT implementation (API keys still from env until full factory wiring).
_PROVIDER_MAP: dict[str, type[STTProvider]] = {
    "openai": OpenAISTTProvider,
    "google": GeminiSTTProvider,
    "google_genai": GeminiSTTProvider,
    "gemini": GeminiSTTProvider,
}


def create_stt_service(workspace_path: Path) -> STTService:
    """Build an STTService from workspace preferences.

    Moved here from server_process.py so the STT package owns its own
    construction logic.
    """
    from hirocli.domain.credential_store import CredentialStore
    from hirocli.domain.model_catalog import get_model_catalog
    from hirocli.domain.preferences import load_preferences, resolve_llm
    from hirocli.domain.workspace import workspace_id_for_path

    prefs = load_preferences(workspace_path)
    wid = workspace_id_for_path(workspace_path)
    store = CredentialStore(workspace_path, wid) if wid is not None else None
    stt_resolved = resolve_llm(prefs, workspace_path, "stt", credential_store=store)

    default_model: str | None = None
    providers: list[STTProvider] = []

    if stt_resolved is not None:
        spec = get_model_catalog().get_model(stt_resolved.model_id)
        if spec is None:
            _log.warning("STT model id not in catalog", model_id=stt_resolved.model_id)
        else:
            cls = _PROVIDER_MAP.get(spec.provider_id)
            if cls is None:
                _log.warning(
                    "Unknown STT provider in catalog for preferences",
                    provider_id=spec.provider_id,
                )
            else:
                default_model = stt_resolved.model_id.split(":", 1)[1]
                providers = [cls()]

    return STTService(providers=providers, default_model=default_model)
