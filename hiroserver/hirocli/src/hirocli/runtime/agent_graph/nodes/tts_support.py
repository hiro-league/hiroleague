"""Pure TTS metering helpers extracted from ``ConversationNodes.tts_node`` (P5)."""

from __future__ import annotations

from typing import Any

from hiro_commons.llm_usage import gemini_usage_aggregate_fallback, modality_token_count

from ..graph_kit import estimate_text_tokens


def metered_text(
    provider: str,
    model: str,
    instructions: str | None,
    text: str,
) -> str:
    """Return the text string priced for token estimation (OpenAI instruction-prefix rule)."""
    if provider == "openai" and model == "gpt-4o-mini-tts" and instructions:
        return f"{instructions}\n{text}"
    return text


def build_tts_usage(
    usage_metadata: dict[str, Any] | None,
    *,
    duration_ms: int | float | None,
    text: str,
) -> dict[str, Any]:
    """Compute TTS usage counters from provider metadata and metered input text."""
    if not isinstance(usage_metadata, dict):
        usage_metadata = {}
    tts_text_tokens = modality_token_count(
        usage_metadata,
        detail_keys=("promptTokensDetails", "prompt_tokens_details"),
        modality="TEXT",
    )
    tts_audio_tokens = modality_token_count(
        usage_metadata,
        detail_keys=("candidatesTokensDetails", "candidates_tokens_details"),
        modality="AUDIO",
    )
    tts_text_tokens, tts_audio_tokens = gemini_usage_aggregate_fallback(
        usage_metadata,
        input_text_tokens=tts_text_tokens,
        output_audio_tokens=tts_audio_tokens,
    )
    return {
        "input_tokens": estimate_text_tokens(text),
        "tts_text_tokens": tts_text_tokens or None,
        "tts_audio_tokens": tts_audio_tokens or None,
        "tts_audio_seconds": (
            duration_ms / 1000 if isinstance(duration_ms, (int, float)) else 0.0
        ),
    }
