"""Unit tests for ``tts_support`` pure helpers (P5; Phase 7b step 5: usage from the voice engine's Speech)."""

from __future__ import annotations

import base64
from types import SimpleNamespace

from hirocli.runtime.agent_graph.nodes.tts_support import (
    REPLY_AUDIO_MEDIA_TYPE,
    build_tts_attachment_and_payload,
    build_tts_usage,
    metered_text,
)
from hirocli.services.voice.kit import Speech


def _profile(provider: str = "google", model: str = "gemini-3.8-flash-tts", style: str = "warm tone"):
    return SimpleNamespace(provider=provider, model_name=model, voice="kore", style=style)


def test_metered_text_prefixes_openai_mini_tts_with_instructions() -> None:
    assert (
        metered_text("openai", "gpt-4o-mini-tts", "Speak warmly", "hello")
        == "Speak warmly\nhello"
    )
    assert metered_text("openai", "gpt-4o-mini-tts", None, "hello") == "hello"
    assert metered_text("openai", "tts-1", "Speak warmly", "hello") == "hello"
    assert metered_text("fake", "gpt-4o-mini-tts", "Speak warmly", "hello") == "hello"


def test_build_tts_usage_reads_the_speech_tokens() -> None:
    speech = Speech(b"", 24000, 1.5, 0.01, True, tokens_in=110, tokens_out=370)
    usage = build_tts_usage(speech, provider="google", model="gemini-3.8-flash-tts", style="", text="hello world")

    assert usage["tts_text_tokens"] == 110
    assert usage["tts_audio_tokens"] == 370
    assert usage["tts_audio_seconds"] == 1.5
    assert usage["input_tokens"] > 0


def test_build_tts_usage_openai_estimate_shape() -> None:
    # OpenAI reports no usage: services/voice estimates text tokens, no audio tokens.
    speech = Speech(b"", 24000, 0.8, None, False, tokens_in=3)
    usage = build_tts_usage(speech, provider="openai", model="gpt-4o-mini-tts", style="calm", text="spoken")

    assert usage["tts_text_tokens"] == 3
    assert usage["tts_audio_tokens"] is None
    assert usage["tts_audio_seconds"] == 0.8


def test_build_tts_attachment_and_payload() -> None:
    speech = Speech(b"", 24000, 1.2, 0.01, True, tokens_in=4, tokens_out=30)
    built = build_tts_attachment_and_payload(b"\x01\x02", speech, _profile(), "hello", reply_id="reply-1")

    assert built.attachment["media_type"] == REPLY_AUDIO_MEDIA_TYPE == "audio/mpeg"
    assert base64.b64decode(built.attachment["audio_b64"]) == b"\x01\x02"
    assert built.payload["reply_id"] == "reply-1"
    assert built.payload["provider"] == "google"
    assert built.payload["model"] == "gemini-3.8-flash-tts"
    assert built.payload["voice"] == "kore"
    assert built.payload["duration_ms"] == 1200
    assert built.payload["input_characters"] == 5
    assert built.payload["input_text_tokens"] == 4
    assert built.payload["output_audio_tokens"] == 30
    assert built.usage_counts["input_tokens"] > 0
