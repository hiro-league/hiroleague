"""OpenAI STT provider — direct AsyncOpenAI integration.

Models offered:
  • gpt-4o-mini-transcribe  (default) — fast, low word-error rate, fewer hallucinations
  • gpt-4o-transcribe                  — higher quality, best accuracy
  • gpt-4o-transcribe-diarize          — speaker identification / segmentation

The openai SDK is imported lazily inside methods so this module can be imported
even when the openai package is not installed (provider will report unavailable).

API key is injected by ``create_stt_service`` (credential store).

Supported audio formats: flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, webm (max 25 MB).
The API infers the format from the filename extension on the uploaded BytesIO.
"""

from __future__ import annotations

import io

from hiro_commons.log import Logger

from .provider import ModelInfo, STTProvider

log = Logger.get("STT.OPENAI")

_DEFAULT_MODEL = "gpt-4o-mini-transcribe"

_MIME_TO_EXT: dict[str, str] = {
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".m4a",
    "audio/x-aac": ".m4a",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/flac": ".flac",
}

_MODELS: list[ModelInfo] = [
    ModelInfo(
        model_id="gpt-4o-mini-transcribe",
        provider="openai",
        display_name="GPT-4o Mini Transcribe",
    ),
    ModelInfo(
        model_id="gpt-4o-transcribe",
        provider="openai",
        display_name="GPT-4o Transcribe",
    ),
    ModelInfo(
        model_id="gpt-4o-transcribe-diarize",
        provider="openai",
        display_name="GPT-4o Transcribe (with Diarization)",
    ),
]


class OpenAISTTProvider(STTProvider):
    """Speech-to-text via OpenAI /audio/transcriptions endpoint.

    Uses AsyncOpenAI directly — no LangChain wrapper, no thread-pool hacks.
    Retries on transient RateLimitError / APIError with exponential backoff.
    """

    def __init__(self, *, api_key: str | None = None) -> None:
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "openai"

    def is_available(self) -> bool:
        if not self._api_key:
            return False
        try:
            import openai  # noqa: F401
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
        language: str | None = None,
        prompt: str | None = None,
        temperature: float = 0.0,
        **kwargs: object,
    ) -> str:
        """Transcribe audio bytes via the OpenAI transcriptions endpoint.

        Args:
            audio_bytes: Raw audio data.
            model:       One of the model_ids from supported_models(). Defaults to
                         gpt-4o-mini-transcribe.
            mime_type:   MIME type of the audio data. Mapped to a filename extension
                         so OpenAI can infer the format correctly.
            language:    Optional ISO-639-1 language hint (e.g. "en") to improve
                         accuracy and reduce latency.
            prompt:      Optional free-text prompt to guide transcription style.
            temperature: Sampling temperature (0.0 = deterministic).
        """
        from openai import AsyncOpenAI, APIError, RateLimitError
        from tenacity import retry, stop_after_attempt, wait_exponential

        effective_model = model or _DEFAULT_MODEL
        client = AsyncOpenAI(api_key=self._api_key)

        ext = _MIME_TO_EXT.get(mime_type, ".m4a")
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = f"audio{ext}"

        log.info(
            "Transcribing via OpenAI",
            model=effective_model,
            mime_type=mime_type,
            filename=audio_file.name,
            bytes=len(audio_bytes),
        )

        @retry(
            reraise=True,
            wait=wait_exponential(min=1, max=20, multiplier=2),
            stop=stop_after_attempt(4),
            retry=lambda exc: isinstance(exc, (RateLimitError, APIError)),
        )
        async def _call() -> str:
            resp = await client.audio.transcriptions.create(
                model=effective_model,
                file=audio_file,
                language=language,
                prompt=prompt,
                temperature=temperature,
            )
            return resp.text

        transcript = await _call()
        log.info("Transcription complete", model=effective_model, chars=len(transcript))
        return transcript
