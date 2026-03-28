"""format_pricing_summary — catalog pricing one-liners."""

from __future__ import annotations

from hirocli.admin.shared.formatters import format_pricing_summary


def test_chat_pricing() -> None:
    s = format_pricing_summary(
        {"input_per_1m_tokens": 2.5, "output_per_1m_tokens": 10.0},
        "chat",
    )
    assert "2.50" in s and "10.00" in s


def test_tts_pricing() -> None:
    s = format_pricing_summary({"per_character": 0.000015}, "tts")
    assert "1K" in s or "chars" in s


def test_empty_pricing() -> None:
    assert format_pricing_summary(None, "chat") == "—"
