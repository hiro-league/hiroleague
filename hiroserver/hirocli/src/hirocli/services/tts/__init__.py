"""Text-to-speech provider package.

Public API
----------
    TTSProvider          — ABC for all TTS providers
    TTSModelInfo         — dataclass describing a single model
    TTSResult            — dataclass carrying synthesis output (audio bytes, MIME, duration)
    TTSService           — orchestrator that aggregates providers and routes by model ID
    OpenAITTSProvider    — OpenAI gpt-4o-mini-tts
    GeminiTTSProvider    — Google Gemini multimodal TTS (preview)
"""

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
]
