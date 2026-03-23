"""TTS provider contract — TTSProvider ABC, TTSModelInfo, and TTSResult.

Every concrete provider:
  1. Declares the models it offers via supported_models().
  2. Reports whether it is usable right now via is_available() (API key present,
     optional SDK installed).
  3. Performs speech synthesis via synthesize().

Provider modules import their SDK dependencies lazily (inside methods), so
importing this module never pulls in openai or google-genai.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class TTSModelInfo:
    """Metadata for a single TTS model offered by a provider.

    Attributes:
        model_id:     Canonical identifier used in API calls and preferences-based resolution.
        provider:     Provider name (matches TTSProvider.name), e.g. "openai", "gemini".
        display_name: Human-readable label for UIs / logs.
    """

    model_id: str
    provider: str
    display_name: str


@dataclass(frozen=True)
class TTSResult:
    """Output of a successful TTS synthesis call.

    Carries everything needed to construct the ``message.voiced`` event payload:
    raw audio bytes, MIME type, duration, and which model/voice produced it.
    """

    audio_bytes: bytes
    mime_type: str
    duration_ms: int
    model: str
    voice: str


class TTSProvider(ABC):
    """Abstract base for text-to-speech providers.

    Concrete providers register themselves with TTSService by passing instances
    to its constructor. TTSService only activates a provider when is_available()
    returns True, so unavailable providers are silently skipped.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this provider, e.g. ``"openai"`` or ``"gemini"``."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True when this provider can be used (API key present, SDK importable)."""

    @abstractmethod
    def supported_models(self) -> list[TTSModelInfo]:
        """Return the list of models this provider offers.

        Called only when is_available() is True.
        """

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        *,
        model: str | None = None,
        voice: str = "",
        instructions: str = "",
        **kwargs: object,
    ) -> TTSResult:
        """Synthesize speech from text and return audio bytes with metadata.

        Args:
            text:         The text to synthesize into speech.
            model:        Model ID to use (must be one from supported_models()).
                          When None the provider uses its own default.
            voice:        Voice name / ID for the provider (e.g. "sage", "Kore").
            instructions: Voice affect/style prompt (provider-specific behavior).
            **kwargs:     Provider-specific options.
        """
