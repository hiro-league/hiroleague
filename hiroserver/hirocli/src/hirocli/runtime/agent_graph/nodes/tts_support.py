"""Pure TTS metering helpers used by ``TTSNodes.tts_node``.

Phase 7b step 5: Hiro's voice replies speak with a voice profile through ``services/voice``, which
returns PCM + its usage (``kit.Speech``); the node encodes MP3 and these helpers build the reply
payload, the ``ReplyAudio`` attachment and the usage counters the ledger prices and counts (provider
"google" / "openai", the model's own name, text/audio tokens, audio seconds, characters).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from ..graph_kit import estimate_text_tokens
from ..state import ReplyAudio

# The app gets MP3: iPhones can't play OGG/Opus (the WhatsApp plugin transcodes MP3 → OGG itself).
REPLY_AUDIO_MEDIA_TYPE = "audio/mpeg"


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


def build_tts_usage(speech: Any, *, provider: str, model: str, style: str, text: str) -> dict[str, Any]:
    """Usage counters for a spoken reply from the provider's ``Speech`` (tokens as the provider
    reported them — Gemini — or as ``services/voice`` estimated them — OpenAI)."""
    return {
        "input_tokens": estimate_text_tokens(metered_text(provider, model, style, text)),
        "tts_text_tokens": int(getattr(speech, "tokens_in", 0) or 0) or None,
        "tts_audio_tokens": int(getattr(speech, "tokens_out", 0) or 0) or None,
        "tts_audio_seconds": float(getattr(speech, "seconds", 0.0) or 0.0),
    }


@dataclass(frozen=True)
class TtsAttachmentAndPayload:
    attachment: ReplyAudio
    payload: dict[str, Any]
    usage_counts: dict[str, Any]


def build_tts_attachment_and_payload(
    mp3: bytes,
    speech: Any,
    profile: Any,
    text: str,
    *,
    reply_id: str,
) -> TtsAttachmentAndPayload:
    """Base64-encode the MP3 and build the ``GRAPH_TTS_COMPLETED`` payload + ``ReplyAudio``.

    ``profile`` is the ``VoiceProfile`` that spoke (provider, model name, voice, style). The payload
    keeps the ``message.voiced`` wire shape the app already reads.
    """
    provider = str(profile.provider)
    model = str(profile.model_name)
    audio_b64 = base64.b64encode(mp3).decode()
    usage_counts = build_tts_usage(speech, provider=provider, model=model, style=profile.style, text=text)
    duration_ms = int(round(usage_counts["tts_audio_seconds"] * 1000))
    payload = {
        "reply_id": reply_id,
        "blob_id": "",
        "media_type": REPLY_AUDIO_MEDIA_TYPE,
        "size": len(mp3),
        "duration_ms": duration_ms,
        "audio_b64": audio_b64,
        "provider": provider,
        "model": model,
        "voice": profile.voice,
        "input_characters": len(text),
        "input_text_tokens": usage_counts["tts_text_tokens"] or usage_counts["input_tokens"],
        "output_audio_tokens": usage_counts["tts_audio_tokens"] or 0,
        "generated_audio_seconds": usage_counts["tts_audio_seconds"],
        # The voice engine reports tokens directly (no provider usage_metadata to re-read).
        "usage_metadata": {},
    }
    attachment: ReplyAudio = {
        "blob_id": "",
        "media_type": REPLY_AUDIO_MEDIA_TYPE,
        "size": len(mp3),
        "duration_ms": duration_ms,
        "media_path": "",
        "audio_b64": audio_b64,
    }
    return TtsAttachmentAndPayload(
        attachment=attachment,
        payload=payload,
        usage_counts=usage_counts,
    )
