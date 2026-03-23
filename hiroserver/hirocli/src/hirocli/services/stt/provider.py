"""STT provider contract — STTProvider ABC and ModelInfo dataclass.

Every concrete provider:
  1. Declares the models it offers via supported_models().
  2. Reports whether it is usable right now via is_available() (API key present,
     optional SDK installed).
  3. Performs the actual transcription via transcribe().

Provider modules import their SDK dependencies lazily (inside methods), so
importing this module never pulls in openai or google-genai.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    """Metadata for a single STT model offered by a provider.

    Attributes:
        model_id:     Canonical identifier used in API calls and preferences-based default resolution.
        provider:     Provider name (matches STTProvider.name), e.g. "openai", "gemini".
        display_name: Human-readable label for UIs / logs.
    """

    model_id: str
    provider: str
    display_name: str


class STTProvider(ABC):
    """Abstract base for speech-to-text providers.

    Concrete providers register themselves with STTService by passing instances
    to its constructor. STTService only activates a provider when is_available()
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
    def supported_models(self) -> list[ModelInfo]:
        """Return the list of models this provider offers.

        Called only when is_available() is True.
        """

    @abstractmethod
    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        model: str | None = None,
        **kwargs: object,
    ) -> str:
        """Transcribe raw audio bytes and return the transcript text.

        Args:
            audio_bytes: Raw audio data (WAV, MP3, M4A, WEBM, etc.).
            model:       Model ID to use (must be one from supported_models()).
                         When None the provider uses its own default.
            **kwargs:    Provider-specific options (language, prompt, temperature, …).
        """
