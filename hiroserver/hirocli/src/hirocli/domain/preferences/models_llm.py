"""LLM default-model selections (``prefs.llm``). Split out of ``models.py`` for readability."""

from __future__ import annotations

from pydantic import BaseModel

from .defaults import (
    DEFAULT_IMAGE_PLAYGROUND_PROFILE_ID,
    pref_field,
)


class LLMPreferences(BaseModel):
    """Which catalog models to use when the workspace has credentials for them, and the AI profiles
    of Hiro's chat and reading pictures.

    Phase 7b step 5: ``default_chat`` + ``default_tuning_profile`` became ``chat_profile`` (one AI
    profile), ``IMAGE_VISION_MODEL`` became ``vision_profile``, and ``default_tts`` moved to voice
    profiles (``voice.hiro_profile``). No backward compatibility: v3 files are converted once
    (``convert_v4``).
    """

    chat_profile: str | None = pref_field(
        ai_profile_ref=True,
        default=None,
        title="Hiro's chat",
        description=(
            "The AI profile Hiro chats with (and the model the other jobs borrow when their own "
            "profile isn't set). A character's own AI profiles come first."
        ),
    )
    vision_profile: str | None = pref_field(
        ai_profile_ref=True,
        default=None,
        title="Reading pictures",
        description="The AI profile that describes pictures sent to Hiro. Empty = pictures aren't read.",
    )
    default_stt: str | None = pref_field(
        model_kind="stt", default=None, title="Default speech-to-text model"
    )
    # Warm-keepalive window (seconds) for outbound HTTPS connections to model providers (OpenAI +
    # DeepSeek, chat + embeddings). Human-paced chat turns are usually >5s apart — the SDK default —
    # so the first provider call each turn re-does a TLS handshake (~1s+); a larger window keeps the
    # connection warm. Applied centrally in ``model_http`` via ``model_factory``. Google, rerankers,
    # and local endpoints are excluded (Google's aiohttp async path rejects the httpx client hook;
    # rerankers expose no hook; localhost is pointless). Capped in practice by each provider's
    # server-side idle timeout (~60-240s), so very large values buy nothing past that. Read at
    # model-build time → takes effect on server restart.
    http_keepalive_s: int = pref_field(
        # Advanced: a shared HTTP-connection tuning knob most users never touch (hidden behind the
        # "show advanced" toggle).
        advanced=True,
        default=300,
        ge=5,
        le=1800,
        step=5,
        title="Provider connection keepalive (seconds)",
        description=(
            "How long idle HTTPS connections to model providers (OpenAI, DeepSeek) are kept warm "
            "before closing. Larger avoids a TLS handshake on the first call of each chat turn "
            "(~1s). Effective ceiling is the provider's own idle timeout (~60-240s). Takes effect "
            "on server restart."
        ),
    )
    # One timeout + retry policy for every cloud model call (chat, STT) on every provider. (Voice
    # replies speak through services/voice since Phase 7b step 5, with its own timeout.)
    # Before this, each SDK used its own: Gemini had NO timeout and 6 attempts (plus 4 more in our
    # STT/TTS wrappers), so a Gemini 503 spell on 2026-11-06 left a chat turn waiting minutes.
    # Applied in model_factory (chat) and the STT builders via model_http.ProviderCallPolicy.
    # Local endpoints (Ollama, LM Studio) are excluded: a slow local model is not an outage.
    request_timeout_s: int = pref_field(
        advanced=True,
        default=180,
        ge=10,
        le=1800,
        step=10,
        title="Provider response timeout (seconds)",
        description=(
            "How long to wait for a cloud model provider to answer (or to send the next part of a "
            "streamed answer) before that attempt counts as failed. Applies to chat and "
            "speech-to-text on every cloud provider. Takes effect on server restart."
        ),
    )
    max_retries: int = pref_field(
        advanced=True,
        default=2,
        ge=0,
        le=6,
        step=1,
        title="Provider retries",
        description=(
            "How many times a failed or timed-out cloud model call (provider overloaded, rate "
            "limited, network error) is retried before the error is reported. 0 = no retry. "
            "Takes effect on server restart."
        ),
    )
    default_image_gen: str | None = pref_field(
        model_kind="chat",
        save_skip=True,
        default=None,
    )
    default_image_profile: str = pref_field(
        save_skip=True,
        default=DEFAULT_IMAGE_PLAYGROUND_PROFILE_ID,
    )
