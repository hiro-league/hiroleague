"""Unit tests for the OpenAI STT provider helpers."""

from __future__ import annotations

import pytest

from hirocli.services.stt.openai_provider import _ext_for_mime


@pytest.mark.parametrize(
    "mime, expected",
    [
        # Bare MIME types — exact dict hits.
        ("audio/webm", ".webm"),
        ("audio/mp4", ".m4a"),
        ("audio/m4a", ".m4a"),
        ("audio/aac", ".m4a"),
        ("audio/ogg", ".ogg"),
        ("audio/wav", ".wav"),
        ("audio/x-wav", ".wav"),
        ("audio/mpeg", ".mp3"),
        ("audio/mp3", ".mp3"),
        ("audio/flac", ".flac"),
        # Parameterised MIME types — must strip ``;codecs=…`` and still resolve.
        # This is the regression: Chrome's MediaRecorder emits this and previously
        # fell through to ``.m4a`` which made OpenAI return 400 "corrupted".
        ("audio/webm;codecs=opus", ".webm"),
        ("audio/webm; codecs=opus", ".webm"),
        ("audio/ogg;codecs=opus", ".ogg"),
        ("audio/mp4; codecs=mp4a.40.2", ".m4a"),
        # Case insensitivity.
        ("Audio/WebM", ".webm"),
        ("AUDIO/MPEG", ".mp3"),
        # Substring fallback for unknown MIME variants.
        ("audio/x-mpeg", ".mp3"),
        ("audio/something-flac", ".flac"),
        # Defaults.
        (None, ".m4a"),
        ("", ".m4a"),
        ("application/octet-stream", ".m4a"),
    ],
)
def test_ext_for_mime(mime: str | None, expected: str) -> None:
    from hirocli.services.stt.openai_provider import _ext_for_mime as fn

    assert fn(mime) == expected


def test_ext_for_mime_returns_dot_prefixed_value() -> None:
    """OpenAI's SDK uses the filename extension to infer container/codec; the
    leading dot is required so ``audio.webm`` (not ``audiowebm``) is sent."""
    assert _ext_for_mime("audio/webm").startswith(".")
    assert _ext_for_mime("audio/webm;codecs=opus").startswith(".")
