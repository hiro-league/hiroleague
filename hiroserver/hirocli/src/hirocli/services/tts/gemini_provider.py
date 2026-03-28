"""Gemini TTS provider — speech synthesis via Google GenAI generate_content().

Models offered:
  - gemini-2.5-flash-preview-tts  (default, preview only via AI Studio / API key)

The generate_content path returns raw PCM audio (24 kHz, 16-bit, mono).
This provider converts it to MP3 via lameenc (Python LAME bindings — no
ffmpeg binary required) for universal playback compatibility.

Note: production Gemini TTS requires the Google Cloud TTS API with GCP project
setup, billing, and IAM — not in scope. The models here are preview-only.

The google-genai SDK and lameenc are imported lazily inside methods so this
module can be imported even when those packages are not installed (provider
will report unavailable).

Enabled when: a Google API key is supplied by the factory and both google-genai
and lameenc are importable.
"""

from __future__ import annotations

import time

from hiro_commons.log import Logger

from .provider import TTSModelInfo, TTSProvider, TTSResult

log = Logger.get("TTS.GEMINI")

_DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"
_DEFAULT_VOICE = "Kore"
_PCM_SAMPLE_RATE = 24000
_PCM_SAMPLE_WIDTH = 2  # 16-bit = 2 bytes
_PCM_CHANNELS = 1

_MODELS: list[TTSModelInfo] = [
    TTSModelInfo(
        model_id="gemini-2.5-flash-preview-tts",
        provider="gemini",
        display_name="Gemini 2.5 Flash TTS (preview)",
    ),
]


def _pcm_duration_ms(pcm_bytes: bytes) -> int:
    """Compute exact duration from PCM byte count."""
    bytes_per_second = _PCM_SAMPLE_RATE * _PCM_SAMPLE_WIDTH * _PCM_CHANNELS
    if bytes_per_second == 0:
        return 0
    return int(len(pcm_bytes) / bytes_per_second * 1000)


def _pcm_to_mp3(pcm_bytes: bytes) -> bytes:
    """Convert raw PCM audio to MP3 via lameenc (no ffmpeg binary needed)."""
    import lameenc

    encoder = lameenc.Encoder()
    encoder.set_channels(_PCM_CHANNELS)
    encoder.set_in_sample_rate(_PCM_SAMPLE_RATE)
    encoder.set_bit_rate(128)
    encoder.set_quality(2)
    return encoder.encode(pcm_bytes) + encoder.flush()


class GeminiTTSProvider(TTSProvider):
    """Text-to-speech via Google Gemini generate_content() with audio modality.

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
            import lameenc  # noqa: F401
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
        """Synthesize speech via Gemini generate_content() with audio response modality.

        Args:
            text:         Text to convert to speech.
            model:        One of the model_ids from supported_models().
            voice:        Gemini voice name (e.g. "Kore", "Puck", "Callirrhoe").
            instructions: Voice style prompt — prepended to the text content
                          (Gemini has no separate instructions parameter).
        """
        from google import genai
        from google.genai import types
        from tenacity import retry, stop_after_attempt, wait_exponential

        effective_model = model or _DEFAULT_MODEL
        effective_voice = voice or _DEFAULT_VOICE

        client = genai.Client(api_key=self._api_key)

        # Gemini has no separate instructions parameter — prepend to text.
        # Always wrap in an explicit TTS instruction to prevent the model from
        # generating text instead of audio (observed with short/ambiguous inputs).
        if instructions:
            synthesis_text = f'{instructions}\nSay the following text aloud:\n"{text}"'
        else:
            synthesis_text = f'Say the following text aloud:\n"{text}"'

        log.info(
            "Synthesizing via Gemini",
            model=effective_model,
            voice=effective_voice,
            text_len=len(text),
            has_instructions=bool(instructions),
        )

        @retry(
            reraise=True,
            wait=wait_exponential(min=1, max=20, multiplier=2),
            stop=stop_after_attempt(4),
        )
        async def _call() -> bytes:
            response = await client.aio.models.generate_content(
                model=effective_model,
                contents=synthesis_text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=effective_voice,
                            )
                        )
                    ),
                ),
            )
            return response.candidates[0].content.parts[0].inline_data.data

        t0 = time.perf_counter()
        pcm_bytes = await _call()
        duration_ms = _pcm_duration_ms(pcm_bytes)

        # Convert raw PCM to MP3 for universal playback
        mp3_bytes = _pcm_to_mp3(pcm_bytes)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        log.info(
            "Synthesis complete",
            model=effective_model,
            voice=effective_voice,
            pcm_bytes=len(pcm_bytes),
            mp3_bytes=len(mp3_bytes),
            duration_ms=duration_ms,
            elapsed_ms=elapsed_ms,
        )

        return TTSResult(
            audio_bytes=mp3_bytes,
            mime_type="audio/mp3",
            duration_ms=duration_ms,
            model=effective_model,
            voice=effective_voice,
        )
