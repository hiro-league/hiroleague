"""Gemini TTS provider — speech synthesis via Google GenAI generate_content().

Models offered (GA since Sep 22, 2026; aistudio.google.com/docs/speech-generation):
  - gemini-3.8-flash-tts        (default)
  - gemini-3.8-flash-lite-tts   (cheaper)
The 3.1 / 2.5 preview TTS models shut down Nov 17, 2026.

Gemini 3.8 TTS differs from the preview models in two ways this provider handles:
  - Unary generate_content returns complete WAV (RIFF header, 24 kHz, 16-bit, mono) instead of raw
    PCM. We unwrap the WAV (raw PCM is still accepted) and convert to MP3 via lameenc (Python LAME
    bindings — no ffmpeg binary required) for universal playback compatibility.
  - The ``text`` is spoken verbatim, so style directions can no longer be written into the text
    (they would be read aloud). Style goes in the part's ``speech_metadata.style``.

Audio output is a v1beta-only API feature: google-genai 3.x defaults to v1, which is why the
dependency is held below 3.0 (see hirocli pyproject).

The google-genai SDK and lameenc are imported lazily inside methods so this
module can be imported even when those packages are not installed (provider
will report unavailable).

Enabled when: a Google API key is supplied by the factory and both google-genai
and lameenc are importable.
"""

from __future__ import annotations

import io
import time
import wave
from typing import Any

from hiro_commons.log import Logger

from .provider import TTSModelInfo, TTSProvider, TTSResult

log = Logger.get("TTS.GEMINI")

_DEFAULT_MODEL = "gemini-3.8-flash-tts"
_DEFAULT_VOICE = "Kore"
_PCM_SAMPLE_RATE = 24000
_PCM_SAMPLE_WIDTH = 2  # 16-bit = 2 bytes
_PCM_CHANNELS = 1

_MODELS: list[TTSModelInfo] = [
    TTSModelInfo(
        model_id="gemini-3.8-flash-tts",
        provider="gemini",
        display_name="Gemini 3.8 Flash TTS",
    ),
    TTSModelInfo(
        model_id="gemini-3.8-flash-lite-tts",
        provider="gemini",
        display_name="Gemini 3.8 Flash-Lite TTS",
    ),
]


class _PcmAudio:
    """16-bit PCM frames plus the format needed to time and encode them."""

    __slots__ = ("frames", "sample_rate", "channels", "sample_width")

    def __init__(self, frames: bytes, sample_rate: int, channels: int, sample_width: int) -> None:
        self.frames = frames
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width


def _decode_audio(data: bytes, mime_type: str | None) -> _PcmAudio:
    """Unwrap Gemini audio into PCM frames.

    Gemini 3.8 TTS returns WAV (``audio/wav``) for unary calls; older/streaming paths return
    headerless ``audio/l16`` PCM at 24 kHz. Detect by MIME type or the RIFF magic bytes. A WAV that
    isn't 16-bit PCM raises ValueError (lameenc only encodes 16-bit input).
    """
    mime = (mime_type or "").lower()
    if data[:4] == b"RIFF" or "wav" in mime:
        try:
            with wave.open(io.BytesIO(data), "rb") as wav:
                audio = _PcmAudio(
                    frames=wav.readframes(wav.getnframes()),
                    sample_rate=wav.getframerate(),
                    channels=wav.getnchannels(),
                    sample_width=wav.getsampwidth(),
                )
        except wave.Error as exc:
            raise ValueError(f"Gemini TTS returned an unreadable WAV ({mime or 'no mime'}): {exc}") from exc
        if audio.sample_width != _PCM_SAMPLE_WIDTH:
            raise ValueError(
                f"Gemini TTS returned {audio.sample_width * 8}-bit audio; only 16-bit PCM is supported"
            )
        return audio
    return _PcmAudio(data, _PCM_SAMPLE_RATE, _PCM_CHANNELS, _PCM_SAMPLE_WIDTH)


def _pcm_duration_ms(audio: _PcmAudio) -> int:
    """Compute exact duration from PCM byte count."""
    bytes_per_second = audio.sample_rate * audio.sample_width * audio.channels
    if bytes_per_second == 0:
        return 0
    return int(len(audio.frames) / bytes_per_second * 1000)


def _pcm_to_mp3(audio: _PcmAudio) -> bytes:
    """Convert 16-bit PCM audio to MP3 via lameenc (no ffmpeg binary needed)."""
    import lameenc

    encoder = lameenc.Encoder()
    encoder.set_channels(audio.channels)
    encoder.set_in_sample_rate(audio.sample_rate)
    encoder.set_bit_rate(128)
    encoder.set_quality(2)
    return encoder.encode(audio.frames) + encoder.flush()


def _synthesis_contents(text: str, instructions: str) -> list[Any]:
    """Build the request contents: the text verbatim, style in ``speech_metadata``.

    Gemini 3.8 TTS reads the ``text`` field strictly as a transcript, so the old
    "Say the following text aloud" wrapper (and any style prefix) would be spoken.
    """
    from google.genai import types

    metadata = types.SpeechMetadata(style=instructions) if instructions else None
    return [types.Content(role="user", parts=[types.Part(text=text, speech_metadata=metadata)])]


def _usage_metadata_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        data = dump(by_alias=True, exclude_none=True)
        return data if isinstance(data, dict) else None
    to_json_dict = getattr(value, "to_json_dict", None)
    if callable(to_json_dict):
        data = to_json_dict()
        return data if isinstance(data, dict) else None
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        data = to_dict()
        return data if isinstance(data, dict) else None
    return None


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
            instructions: Voice style direction (e.g. "warm and calm"), sent as the
                          part's ``speech_metadata.style``; never mixed into the text.
        """
        from google import genai
        from google.genai import types
        from tenacity import retry, stop_after_attempt, wait_exponential

        effective_model = model or _DEFAULT_MODEL
        effective_voice = voice or _DEFAULT_VOICE

        client = genai.Client(api_key=self._api_key)

        synthesis_contents = _synthesis_contents(text, instructions)

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
        async def _call() -> tuple[bytes, str | None, dict[str, Any] | None]:
            response = await client.aio.models.generate_content(
                model=effective_model,
                contents=synthesis_contents,
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
            blob = response.candidates[0].content.parts[0].inline_data
            usage = _usage_metadata_dict(getattr(response, "usage_metadata", None))
            return blob.data, blob.mime_type, usage

        t0 = time.perf_counter()
        audio_data, audio_mime, usage_metadata = await _call()
        # 3.8 TTS returns WAV; unwrap to PCM so duration and MP3 use the real format.
        pcm = _decode_audio(audio_data, audio_mime)
        duration_ms = _pcm_duration_ms(pcm)

        # Convert PCM to MP3 for universal playback
        mp3_bytes = _pcm_to_mp3(pcm)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        log.info(
            "Synthesis complete",
            model=effective_model,
            voice=effective_voice,
            audio_mime=audio_mime,
            pcm_bytes=len(pcm.frames),
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
            provider=self.name,
            usage_metadata=usage_metadata,
        )
