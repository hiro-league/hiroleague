"""Speech-to-text provider package.

Public API
----------
    STTProvider     — ABC for all STT providers
    ModelInfo       — dataclass describing a single model
    STTService      — orchestrator that aggregates providers and routes by model ID
    OpenAISTTProvider — OpenAI gpt-4o-transcribe family
    GeminiSTTProvider — Google Gemini multimodal transcription
"""

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
]
