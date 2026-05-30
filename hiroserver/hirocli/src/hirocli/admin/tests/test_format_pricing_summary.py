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
    s = format_pricing_summary({"estimated_usd_per_1k_chars_speech": 0.018}, "tts")
    assert "0.018" in s
    assert "/1K characters" in s


def test_tts_pricing_per_character_fallback() -> None:
    s = format_pricing_summary({"per_character": 0.000015}, "tts")
    assert "1K characters" in s


def test_empty_pricing() -> None:
    assert format_pricing_summary(None, "chat") == "—"


def test_rerank_cohere_per_search_pricing() -> None:
    s = format_pricing_summary({"estimated_usd_per_1k_searches": 2.50}, "rerank")
    assert s == "$2.50/1K searches"


def test_rerank_voyage_processed_tokens_and_request_estimate() -> None:
    s = format_pricing_summary(
        {
            "per_1k_tokens": 0.00005,
            "input_per_1m_tokens": 0.05,
            "estimated_usd_per_request": 0.0025,
        },
        "rerank",
    )
    assert "0.00005" in s and "1K processed tokens" in s and "0.0025" in s
    assert "\n" in s


def test_rerank_voyage_null_per_1k_searches_not_zero_dollars() -> None:
    """API model_dump includes null for unused pricing fields — must not format as $0.00/1K searches."""
    s = format_pricing_summary(
        {
            "per_1k_tokens": 0.00005,
            "input_per_1m_tokens": 0.05,
            "estimated_usd_per_request": 0.0025,
            "estimated_usd_per_1k_searches": None,
        },
        "rerank",
    )
    assert "searches" not in s
    assert "1K processed tokens" in s
