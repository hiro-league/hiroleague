"""Unit tests for ``ledger.pricing.price_row``."""

from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.domain.model_catalog import get_model_catalog
from hirocli.runtime.agent_graph.ledger.pricing import price_row


@pytest.fixture
def catalog():
    return get_model_catalog()


def test_rerank_branch_uses_input_tokens(catalog) -> None:
    priced = price_row(
        {
            "provider": "voyage",
            "model": "voyage:rerank-2.5",
            "input_tokens": 500,
        },
        catalog,
    )
    assert priced["cost_usd"] not in ("", None)
    assert priced["pricing_version"]


def test_stt_duration_fallback(catalog) -> None:
    priced = price_row(
        {
            "provider": "openai",
            "model": "openai:gpt-4o-transcribe",
            "stt_audio_seconds": 12.5,
        },
        catalog,
    )
    assert priced["cost_usd"] == "0.00125"
    assert priced["pricing_version"]


def test_stt_token_path(catalog) -> None:
    priced = price_row(
        {
            "provider": "openai",
            "model": "openai:gpt-4o-mini-transcribe",
            "stt_audio_seconds": 8.4,
            "stt_audio_tokens": 1200,
            "output_tokens": 80,
        },
        catalog,
    )
    assert priced["cost_usd"] == "0.0019"
    assert priced["pricing_version"]


def test_tts_gemini_with_audio_tokens(catalog) -> None:
    priced = price_row(
        {
            "provider": "gemini",
            "model": "gemini-2.5-flash-preview-tts",
            "tts_chars": 80,
            "tts_text_tokens": 18,
            "tts_audio_tokens": 240,
            "tts_audio_seconds": 4.0,
            "input_tokens": 18,
        },
        catalog,
    )
    assert priced["cost_usd"] not in ("", None)
    assert float(priced["cost_usd"]) > 0
    assert priced["pricing_version"]


def test_tts_gemini_without_audio_tokens_unpriced(catalog) -> None:
    priced = price_row(
        {
            "provider": "gemini",
            "model": "gemini-2.5-flash-preview-tts",
            "tts_chars": 80,
            "tts_text_tokens": 18,
            "tts_audio_seconds": 4.0,
            "input_tokens": 18,
        },
        catalog,
    )
    assert priced["cost_usd"] == ""
    assert priced["pricing_version"] == ""


def test_token_usage_default_branch(catalog) -> None:
    priced = price_row(
        {
            "provider": "openai",
            "model": "openai:gpt-5.4",
            "input_tokens": 100,
            "output_tokens": 20,
            "cached_input_tokens": 10,
        },
        catalog,
    )
    assert priced["cost_usd"] not in ("", None)
    assert priced["pricing_version"]


def test_no_model_skips_pricing(catalog) -> None:
    priced = price_row({"provider": "openai", "input_tokens": 10}, catalog)
    assert priced["cost_usd"] == ""
    assert priced["pricing_version"] == ""
