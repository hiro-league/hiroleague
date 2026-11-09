"""What speaking needs to know (Phase 7b): OpenAI's voices, Gemini's sound tags, the length limit, prices.

OpenAI's voices come from the catalog (``tts_voices`` of the ``openai`` provider). Gemini's voices are
fetched from its API (``gemini_speech.voices``). Prices come from the catalog
(``estimate_tts_usage_cost``), the same as Hiro's own spoken replies in the graph ledger.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ...domain.model_catalog import get_model_catalog

MAX_CHARS = 4096  # OpenAI's speech limit; used for Gemini too (it publishes none)
# OpenAI reports no usage for speech: ~1250 audio tokens a minute (its launch post) and ~4 characters a token.
CHARS_PER_TOKEN = 4

# Gemini 3.8's inline sound tags, grouped as Google's docs group them (they stay in English whatever the
# language of the text). OpenAI would read them aloud, so they are taken out for it.
TAG_GROUPS: dict[str, list[str]] = {
    "Pauses": ["short pause", "long pause"],
    "Laughter": ["laugh", "laughter", "chuckle", "chuckles", "giggle", "cackle", "snicker"],
    "Breath": ["breath", "heavy breath", "exhales", "cough", "throat-clearing"],
    "Other": [
        "sigh", "sighs", "whispers", "whispering", "cheer", "shout", "phew", "pff", "tsk", "hiss", "grr", "sneeze",
        "snort",
    ],
    "Distress": [
        "gasp", "cry", "sob", "whimper", "groan", "moan", "grunt", "growl", "pant", "yawn", "scream", "shriek",
        "argh",
    ],
}
COMMON_TAGS = ["short pause", "long pause", "laugh", "chuckle", "sigh", "breath", "gasp", "whispers"]
_TAG_RE = re.compile(r"\s*<(" + "|".join(re.escape(t) for g in TAG_GROUPS.values() for t in g) + r")>", re.I)


@dataclass(frozen=True)
class Speech:
    """What a provider said: PCM (16-bit mono) and what it cost."""

    pcm: bytes
    rate: int
    seconds: float
    cost_usd: float | None  # None: the catalog has no price for the model (counted as unpriced)
    cost_exact: bool  # False = estimated (OpenAI reports no usage)
    tokens_in: int = 0
    tokens_out: int = 0


def strip_tags(text: str) -> str:
    """Remove Gemini's sound tags (only the known ones, so text like "<3" survives)."""
    return re.sub(r"  +", " ", _TAG_RE.sub("", text)).strip()


def openai_voices() -> list[str]:
    provider = get_model_catalog().get_provider("openai")
    return [v.id for v in (provider.tts_voices if provider else [])]


def speech_cost(
    provider: str,
    model: str,
    *,
    characters: int = 0,
    text_tokens: int = 0,
    audio_seconds: float = 0.0,
    audio_tokens: int = 0,
) -> float | None:
    """USD from the catalog's prices; None when the catalog has no price for this model."""
    estimate = get_model_catalog().estimate_tts_usage_cost(
        provider_id=provider,
        model_id=model,
        input_characters=characters,
        input_text_tokens=text_tokens,
        generated_audio_seconds=audio_seconds,
        output_audio_tokens=audio_tokens,
    )
    return estimate.estimated_total if estimate.pricing_available else None
