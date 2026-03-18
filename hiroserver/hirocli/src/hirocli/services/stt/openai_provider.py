"""OpenAI STT provider — direct AsyncOpenAI integration.

Models offered:
  • gpt-4o-mini-transcribe  (default) — fast, low word-error rate, fewer hallucinations
  • gpt-4o-transcribe                  — higher quality, best accuracy
  • gpt-4o-transcribe-diarize          — speaker identification / segmentation

The openai SDK is imported lazily inside methods so this module can be imported
even when the openai package is not installed (provider will report unavailable).

Enabled when: OPENAI_API_KEY environment variable is set.

Supported audio formats: mp3, mp4, mpeg, mpga, m4a, wav, webm (max 25 MB).
"""

from __future__ import annotations

import io
import os

from hiro_commons.log import Logger

from .provider import ModelInfo, STTProvider

log = Logger.get("STT.OPENAI")

_DEFAULT_MODEL = "gpt-4o-mini-transcribe"

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

    @property
    def name(self) -> str:
        return "openai"

    def is_available(self) -> bool:
        if not os.environ.get("OPENAI_API_KEY"):
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
        language: str | None = None,
        prompt: str | None = None,
        temperature: float = 0.0,
        filename: str = "audio.wav",
        **kwargs: object,
    ) -> str:
        """Transcribe audio bytes via the OpenAI transcriptions endpoint.

        Args:
            audio_bytes: Raw audio data.
            model:       One of the model_ids from supported_models(). Defaults to
                         gpt-4o-mini-transcribe.
            language:    Optional ISO-639-1 language hint (e.g. "en") to improve
                         accuracy and reduce latency.
            prompt:      Optional free-text prompt to guide transcription style.
            temperature: Sampling temperature (0.0 = deterministic).
            filename:    Hint for the audio format via file extension. The OpenAI
                         API uses the filename extension to infer format.
        """
        from openai import AsyncOpenAI, APIError, RateLimitError
        from tenacity import retry, stop_after_attempt, wait_exponential

        effective_model = model or _DEFAULT_MODEL
        api_key = os.environ.get("OPENAI_API_KEY")
        client = AsyncOpenAI(api_key=api_key)

        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename

        log.info("Transcribing via OpenAI", model=effective_model, bytes=len(audio_bytes))

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
