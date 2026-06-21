"""Pure TTS metering helpers used by ``TTSNodes.tts_node``."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from hiro_commons.llm_usage import gemini_usage_aggregate_fallback, modality_token_count

from ..graph_kit import estimate_text_tokens
from ..state import ReplyAudio


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


@dataclass(frozen=True)
class TtsAttachmentAndPayload:
    attachment: ReplyAudio
    payload: dict[str, Any]
    usage_counts: dict[str, Any]


def build_tts_attachment_and_payload(
    result: Any,
    resolved: Any,
    text: str,
    *,
    reply_id: str,
) -> TtsAttachmentAndPayload:
    """Base64-encode audio and build the ``GRAPH_TTS_COMPLETED`` payload + ``ReplyAudio``."""
    audio_b64 = base64.b64encode(result.audio_bytes).decode()
    duration_ms = result.duration_ms
    provider = str(getattr(result, "provider", "") or "")
    usage_metadata = getattr(result, "usage_metadata", None)
    if not isinstance(usage_metadata, dict):
        usage_metadata = {}
    metered = metered_text(provider, result.model, resolved.instructions, text)
    usage_counts = build_tts_usage(
        usage_metadata, duration_ms=duration_ms, text=metered
    )
    payload = {
        "reply_id": reply_id,
        "blob_id": "",
        "media_type": result.mime_type,
        "size": len(result.audio_bytes),
        "duration_ms": duration_ms,
        "audio_b64": audio_b64,
        "provider": provider,
        "model": result.model,
        "voice": result.voice,
        "input_characters": len(text),
        "input_text_tokens": usage_counts["input_tokens"],
        "generated_audio_seconds": usage_counts["tts_audio_seconds"],
        "usage_metadata": usage_metadata,
    }
    attachment: ReplyAudio = {
        "blob_id": "",
        "media_type": result.mime_type,
        "size": len(result.audio_bytes),
        "duration_ms": duration_ms,
        "media_path": "",
        "audio_b64": audio_b64,
    }
    return TtsAttachmentAndPayload(
        attachment=attachment,
        payload=payload,
        usage_counts=usage_counts,
    )
