"""Gemini STT provider — audio transcription via Google GenAI SDK.

Models offered:
  • gemini-2.5-flash        (default, stable) — best price-performance, audio input supported
  • gemini-3-flash-preview  (preview) — frontier multimodal, advanced capabilities
  • gemini-3.1-flash-lite-preview (preview) — cost-efficient, high-volume

Gemini does not expose a dedicated transcription endpoint. Instead we pass the
audio bytes as a multimodal Part alongside a verbatim-transcription instruction
via generate_content(). The prompt is tuned to suppress summarisation and return
only the spoken text.

The google-genai SDK is imported lazily inside methods so this module can be
imported even when the SDK is not installed (provider will report unavailable).

API key is injected by ``create_stt_service`` (credential store).
"""

from __future__ import annotations

from hiro_commons.log import Logger

from .provider import ModelInfo, STTProvider

log = Logger.get("STT.GEMINI")

_DEFAULT_MODEL = "gemini-2.5-flash"

_TRANSCRIPTION_PROMPT = (
    "Transcribe the following audio clip verbatim. "
    "Return only the spoken words — no summaries, no commentary, no timestamps. "
    "If the audio is silent or contains no speech, return an empty string."
)

# Model IDs must match the actual Gemini API model codes exactly.
# Gemini 3.x models are preview-only and require the -preview suffix.
_MODELS: list[ModelInfo] = [
    ModelInfo(
        model_id="gemini-2.5-flash",
        provider="gemini",
        display_name="Gemini 2.5 Flash (stable)",
    ),
    ModelInfo(
        model_id="gemini-3-flash-preview",
        provider="gemini",
        display_name="Gemini 3 Flash (preview)",
    ),
    ModelInfo(
        model_id="gemini-3.1-flash-lite-preview",
        provider="gemini",
        display_name="Gemini 3.1 Flash-Lite (preview)",
    ),
]


class GeminiSTTProvider(STTProvider):
    """Speech-to-text via Google Gemini multimodal generate_content().

    Uses the async google-genai client directly.
    Retries on transient errors with exponential backoff.
    """

    def __init__(self, *, api_key: str | None = None) -> None:
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "gemini"

    def is_available(self) -> bool:
        if not self._api_key:
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
                         gemini-2.5-flash.
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

        client = genai.Client(api_key=self._api_key)

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
