"""OpenAI TTS provider — speech synthesis via the /audio/speech endpoint.

Models offered:
  - gpt-4o-mini-tts  (default) — compact, fast, supports voice instructions

Output format: MP3 (universally playable on iOS, Android, and web including Firefox).

The openai SDK is imported lazily inside methods so this module can be imported
even when the openai package is not installed (provider will report unavailable).

API key is passed in by the TTS factory (credential store); optional for tests.
"""

from __future__ import annotations

import time

from hiro_commons.log import Logger

from .provider import TTSModelInfo, TTSProvider, TTSResult

log = Logger.get("TTS.OPENAI")

_DEFAULT_MODEL = "gpt-4o-mini-tts"
_DEFAULT_VOICE = "sage"
_OUTPUT_FORMAT = "mp3"

_MODELS: list[TTSModelInfo] = [
    TTSModelInfo(
        model_id="gpt-4o-mini-tts",
        provider="openai",
        display_name="GPT-4o Mini TTS",
    ),
]


def _estimate_mp3_duration_ms(audio_bytes: bytes, bitrate_kbps: int = 128) -> int:
    """Estimate MP3 duration from byte count assuming constant bitrate."""
    if not audio_bytes:
        return 0
    return int(len(audio_bytes) * 8 / bitrate_kbps)


class OpenAITTSProvider(TTSProvider):
    """Text-to-speech via OpenAI /audio/speech endpoint.

    Uses AsyncOpenAI directly — no LangChain wrapper.
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

    def supported_models(self) -> list[TTSModelInfo]:
        return list(_MODELS)

    async def synthesize(
        self,
        text: str,
        *,
        model: str | None = None,
        voice: str = "",
        instructions: str = "",
        **kwargs: object,
    ) -> TTSResult:
        """Synthesize speech via the OpenAI audio.speech.create() endpoint.

        Args:
            text:         Text to convert to speech (max 4096 chars per call).
            model:        One of the model_ids from supported_models().
            voice:        OpenAI voice name (e.g. "sage", "ballad", "marin").
            instructions: Voice affect prompt — controls accent, pacing, emotion.
                          Only works with gpt-4o-mini-tts.
        """
        from openai import APIError, AsyncOpenAI, RateLimitError
        from tenacity import retry, stop_after_attempt, wait_exponential

        effective_model = model or _DEFAULT_MODEL
        effective_voice = voice or _DEFAULT_VOICE

        client = AsyncOpenAI(api_key=self._api_key)

        log.info(
            "Synthesizing via OpenAI",
            model=effective_model,
            voice=effective_voice,
            text_len=len(text),
            has_instructions=bool(instructions),
        )

        @retry(
            reraise=True,
            wait=wait_exponential(min=1, max=20, multiplier=2),
            stop=stop_after_attempt(4),
            retry=lambda exc: isinstance(exc, (RateLimitError, APIError)),
        )
        async def _call() -> bytes:
            create_kwargs: dict = {
                "model": effective_model,
                "input": text,
                "voice": effective_voice,
                "response_format": _OUTPUT_FORMAT,
            }
            # instructions param only supported on gpt-4o-mini-tts
            if instructions and effective_model == "gpt-4o-mini-tts":
                create_kwargs["instructions"] = instructions

            resp = await client.audio.speech.create(**create_kwargs)
            audio_bytes = getattr(resp, "content", None)
            if audio_bytes:
                return audio_bytes
            return b"".join([chunk async for chunk in resp.iter_bytes()])

        t0 = time.perf_counter()
        audio_bytes = await _call()
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        duration_ms = _estimate_mp3_duration_ms(audio_bytes)

        log.info(
            "Synthesis complete",
            model=effective_model,
            voice=effective_voice,
            audio_bytes=len(audio_bytes),
            duration_ms=duration_ms,
            elapsed_ms=elapsed_ms,
        )

        return TTSResult(
            audio_bytes=audio_bytes,
            mime_type="audio/mp3",
            duration_ms=duration_ms,
            model=effective_model,
            voice=effective_voice,
        )
