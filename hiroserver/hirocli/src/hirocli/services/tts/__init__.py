"""Text-to-speech provider package.

Public API
----------
    TTSProvider          — ABC for all TTS providers
    TTSModelInfo         — dataclass describing a single model
    TTSResult            — dataclass carrying synthesis output (audio bytes, MIME, duration)
    TTSService           — orchestrator that aggregates providers and routes by model ID
    OpenAITTSProvider    — OpenAI gpt-4o-mini-tts
    GeminiTTSProvider    — Google Gemini multimodal TTS (preview)
    create_tts_service   — factory that builds a TTSService from workspace preferences
"""

from __future__ import annotations

from pathlib import Path

from hiro_commons.log import Logger

from .gemini_provider import GeminiTTSProvider
from .openai_provider import OpenAITTSProvider
from .provider import TTSModelInfo, TTSProvider, TTSResult
from .service import TTSService

__all__ = [
    "TTSProvider",
    "TTSModelInfo",
    "TTSResult",
    "TTSService",
    "OpenAITTSProvider",
    "GeminiTTSProvider",
    "create_tts_service",
]

_log = Logger.get("TTS")

# Provider name (from preferences.json VoiceOption.provider) → provider class.
_PROVIDER_MAP: dict[str, type[TTSProvider]] = {
    "openai": OpenAITTSProvider,
    "google_genai": GeminiTTSProvider,
    "gemini": GeminiTTSProvider,
}


def create_tts_service(workspace_path: Path) -> TTSService | None:
    """Build a TTSService from workspace preferences, or None if TTS is disabled.

    Moved here from server_process.py so the TTS package owns its own
    construction logic.
    """
    from hirocli.domain.preferences import load_preferences, resolve_voice

    prefs = load_preferences(workspace_path)
    if not prefs.audio.agent_replies_in_voice:
        _log.info("TTS disabled in preferences (agent_replies_in_voice=false)")
        return None
    voice = resolve_voice(prefs)
    if not voice:
        _log.warning("TTS enabled but no voice configured — TTS disabled")
        return None
    cls = _PROVIDER_MAP.get(voice.provider)
    if cls is None:
        _log.warning("Unknown TTS provider in preferences, loading none", provider=voice.provider)
        return None
    providers: list[TTSProvider] = [cls()]
    return TTSService(providers=providers, default_model=voice.model)
