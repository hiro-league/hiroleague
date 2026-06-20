"""Unit tests for ``tts_support`` pure helpers (P5)."""

from __future__ import annotations

from types import MappingProxyType

from hirocli.runtime.agent_graph.nodes.tts_support import build_tts_usage, metered_text


def test_metered_text_prefixes_openai_mini_tts_with_instructions() -> None:
    assert (
        metered_text("openai", "gpt-4o-mini-tts", "Speak warmly", "hello")
        == "Speak warmly\nhello"
    )
    assert metered_text("openai", "gpt-4o-mini-tts", None, "hello") == "hello"
    assert metered_text("openai", "tts-1", "Speak warmly", "hello") == "hello"
    assert metered_text("fake", "gpt-4o-mini-tts", "Speak warmly", "hello") == "hello"


def test_build_tts_usage_gemini_modality_details() -> None:
    meta = {
        "promptTokensDetails": (
            MappingProxyType({"modality": "TEXT", "tokenCount": 110}),
        ),
        "candidatesTokensDetails": (
            MappingProxyType({"modality": "AUDIO", "tokenCount": 370}),
        ),
    }
    usage = build_tts_usage(meta, duration_ms=1500, text="hello world")

    assert usage["tts_text_tokens"] == 110
    assert usage["tts_audio_tokens"] == 370
    assert usage["tts_audio_seconds"] == 1.5
    assert usage["input_tokens"] > 0


def test_build_tts_usage_empty_metadata_uses_aggregate_fallback() -> None:
    meta = {"promptTokenCount": 92, "candidatesTokenCount": 89}
    usage = build_tts_usage(meta, duration_ms=None, text="x")

    assert usage["tts_text_tokens"] == 92
    assert usage["tts_audio_tokens"] == 89
    assert usage["tts_audio_seconds"] == 0.0


def test_build_tts_usage_openai_empty_shape() -> None:
    usage = build_tts_usage({}, duration_ms=800, text="spoken")

    assert usage["tts_text_tokens"] is None
    assert usage["tts_audio_tokens"] is None
    assert usage["tts_audio_seconds"] == 0.8
