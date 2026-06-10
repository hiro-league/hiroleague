"""Image-generation provider contract — ImageGenProvider ABC, ImageGenModelInfo, ImageGenResult.

Mirrors the TTS provider contract (`services/tts/provider.py`):
  1. Providers declare their models via supported_models().
  2. Report usability via is_available() (credentials present).
  3. Generate images via generate().

Provider modules import their HTTP/SDK dependencies lazily so importing this
module stays cheap.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ImageGenModelInfo:
    """Metadata for a single image-gen model offered by a provider.

    Attributes:
        model_id:     Short id used in API calls / preference resolution (catalog id minus
                      the ``provider:`` prefix), e.g. ``"flux-1-schnell"``.
        provider:     Provider name (matches ImageGenProvider.name), e.g. ``"cloudflare"``.
        display_name: Human-readable label for UIs / logs.
    """

    model_id: str
    provider: str
    display_name: str


@dataclass(frozen=True)
class ImageGenResult:
    """Output of a successful image generation call."""

    image_bytes: bytes
    mime_type: str
    model: str
    provider: str
    steps: int
    seed: int | None
    # Actual output resolution when the provider reports/fixes it (flux-1-schnell: 1024x1024).
    width: int | None = None
    height: int | None = None
    elapsed_ms: int = 0
    usage_metadata: dict[str, Any] | None = None


class ImageGenProvider(ABC):
    """Abstract base for text-to-image providers.

    Concrete providers register themselves with ImageGenService by passing instances
    to its constructor. The service only activates a provider when is_available()
    returns True, so unconfigured providers are silently skipped.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this provider, e.g. ``"cloudflare"``."""

    @abstractmethod
    def is_available(self) -> bool:
        """True when this provider can be used (credentials present)."""

    @abstractmethod
    def supported_models(self) -> list[ImageGenModelInfo]:
        """Models this provider offers. Called only when is_available() is True."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        steps: int = 4,
        size: str | None = None,
        seed: int | None = None,
        **kwargs: object,
    ) -> ImageGenResult:
        """Generate an image from text and return raw bytes with metadata.

        Args:
            prompt: Final text prompt (profile scaffolding already applied by the caller).
            model:  Model id from supported_models(); None → provider default.
            steps:  Diffusion steps — providers clamp to their own valid range.
            size:   "WIDTHxHEIGHT" hint; fixed-resolution providers ignore it.
            seed:   Reproducibility seed; None → provider picks randomly.
        """
