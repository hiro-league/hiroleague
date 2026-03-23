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

# Provider name (from preferences.json LLMEntry.provider) → provider class.
_PROVIDER_MAP: dict[str, type[STTProvider]] = {
    "openai": OpenAISTTProvider,
    "google_genai": GeminiSTTProvider,
    "gemini": GeminiSTTProvider,
}


def create_stt_service(workspace_path: Path) -> STTService:
    """Build an STTService from workspace preferences.

    Moved here from server_process.py so the STT package owns its own
    construction logic.
    """
    from hirocli.domain.preferences import load_preferences, resolve_llm

    prefs = load_preferences(workspace_path)
    stt_llm = resolve_llm(prefs, "stt")

    default_model = stt_llm.model if stt_llm else None
    providers: list[STTProvider] = []

    if stt_llm is not None:
        cls = _PROVIDER_MAP.get(stt_llm.provider)
        if cls is None:
            _log.warning("Unknown STT provider in preferences, loading none", provider=stt_llm.provider)
        else:
            providers = [cls()]

    return STTService(providers=providers, default_model=default_model)
