"""Gemini STT provider — audio transcription via Google GenAI SDK.

Models offered:
  • gemini-3.1-flash-lite  (default) — cost-efficient, high-volume, improved audio quality
  • gemini-3-flash                    — powerful multimodal, advanced capabilities
  • gemini-3.1-pro                    — reasoning-first, 1M token context

Gemini does not expose a dedicated transcription endpoint. Instead we pass the
audio bytes as a multimodal Part alongside a verbatim-transcription instruction
via generate_content(). The prompt is tuned to suppress summarisation and return
only the spoken text.

The google-genai SDK is imported lazily inside methods so this module can be
imported even when the SDK is not installed (provider will report unavailable).

Enabled when: GOOGLE_API_KEY or GEMINI_API_KEY environment variable is set.
"""

from __future__ import annotations

import os

from hiro_commons.log import Logger

from .provider import ModelInfo, STTProvider

log = Logger.get("STT.GEMINI")

_DEFAULT_MODEL = "gemini-3.1-flash-lite"

_TRANSCRIPTION_PROMPT = (
    "Transcribe the following audio clip verbatim. "
    "Return only the spoken words — no summaries, no commentary, no timestamps. "
    "If the audio is silent or contains no speech, return an empty string."
)

_MODELS: list[ModelInfo] = [
    ModelInfo(
        model_id="gemini-3.1-flash-lite",
        provider="gemini",
        display_name="Gemini 3.1 Flash-Lite",
    ),
    ModelInfo(
        model_id="gemini-3-flash",
        provider="gemini",
        display_name="Gemini 3 Flash",
    ),
    ModelInfo(
        model_id="gemini-3.1-pro",
        provider="gemini",
        display_name="Gemini 3.1 Pro",
    ),
]


def _api_key() -> str | None:
    return os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")


class GeminiSTTProvider(STTProvider):
    """Speech-to-text via Google Gemini multimodal generate_content().

    Uses the async google-genai client directly.
    Retries on transient errors with exponential backoff.
    """

    @property
    def name(self) -> str:
        return "gemini"

    def is_available(self) -> bool:
        if not _api_key():
            return False
        try:
            import google.genai  # noqa: F401
            return True
        except ImportError:
            return False

    def supported_models(self) -> list[ModelInfo]:
        return list(_MODELS)

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        model: str | None = None,
        mime_type: str = "audio/mp4",
        prompt: str | None = None,
        **kwargs: object,
    ) -> str:
        """Transcribe audio bytes using Gemini generate_content().

        Args:
            audio_bytes: Raw audio data.
            model:       One of the model_ids from supported_models(). Defaults to
                         gemini-3.1-flash-lite.
            mime_type:   MIME type of the audio data (e.g. "audio/mp4",
                         "audio/webm"). Passed to Gemini's Part.from_bytes().
            prompt:      Custom transcription instruction. Defaults to the built-in
                         verbatim transcription prompt.
        """
        from google import genai
        from google.genai import types
        from tenacity import retry, stop_after_attempt, wait_exponential

        effective_model = model or _DEFAULT_MODEL
        effective_prompt = prompt or _TRANSCRIPTION_PROMPT

        client = genai.Client(api_key=_api_key())

        log.info(
            "Transcribing via Gemini",
            model=effective_model,
            mime_type=mime_type,
            bytes=len(audio_bytes),
        )

        @retry(
            reraise=True,
            wait=wait_exponential(min=1, max=20, multiplier=2),
            stop=stop_after_attempt(4),
        )
        async def _call() -> str:
            response = await client.aio.models.generate_content(
                model=effective_model,
                contents=[
                    effective_prompt,
                    types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                ],
            )
            return (response.text or "").strip()

        transcript = await _call()
        log.info("Transcription complete", model=effective_model, chars=len(transcript))
        return transcript
