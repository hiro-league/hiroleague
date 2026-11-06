"""Unit tests for the Gemini TTS provider helpers (Gemini 3.8 TTS request/response shape)."""

from __future__ import annotations

import io
import wave

import pytest

from hirocli.services.tts.gemini_provider import (
    _decode_audio,
    _pcm_duration_ms,
    _pcm_to_mp3,
    _synthesis_contents,
)


def _wav(frames: bytes, *, rate: int = 24000, width: int = 2, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(frames)
    return buf.getvalue()


def test_wav_output_is_unwrapped_to_pcm() -> None:
    # Gemini 3.8 TTS returns WAV for unary calls; the RIFF header must not be encoded as audio.
    pcm = b"\x01\x00" * 24000  # 1 s of 16-bit mono at 24 kHz
    audio = _decode_audio(_wav(pcm), "audio/wav")
    assert audio.frames == pcm
    assert (audio.sample_rate, audio.channels, audio.sample_width) == (24000, 1, 2)
    assert _pcm_duration_ms(audio) == 1000
    assert _pcm_to_mp3(audio)  # encodes without error


def test_wav_detected_by_magic_bytes_and_real_rate_used() -> None:
    audio = _decode_audio(_wav(b"\x00\x00" * 8000, rate=8000), None)
    assert audio.sample_rate == 8000
    assert _pcm_duration_ms(audio) == 1000


def test_raw_pcm_still_accepted() -> None:
    pcm = b"\x00\x00" * 12000
    audio = _decode_audio(pcm, "audio/l16;rate=24000")
    assert audio.frames == pcm
    assert _pcm_duration_ms(audio) == 500


def test_non_16bit_wav_is_rejected() -> None:
    with pytest.raises(ValueError, match="16-bit"):
        _decode_audio(_wav(b"\x00" * 100, width=1), "audio/wav")


def test_text_is_sent_verbatim_with_style_in_speech_metadata() -> None:
    # 3.8 TTS speaks the text field verbatim — no "Say the following" wrapper, style in metadata.
    contents = _synthesis_contents("Hello there.", "warm and calm")
    part = contents[0].parts[0]
    assert part.text == "Hello there."
    assert part.speech_metadata is not None and part.speech_metadata.style == "warm and calm"

    plain = _synthesis_contents("Hi.", "")[0].parts[0]
    assert plain.text == "Hi."
    assert plain.speech_metadata is None
