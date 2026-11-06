"""LLM default-model selections (``prefs.llm``). Split out of ``models.py`` for readability."""

from __future__ import annotations

from pydantic import BaseModel

from .defaults import (
    DEFAULT_CHAT_TUNING_PROFILE_ID,
    DEFAULT_IMAGE_PLAYGROUND_PROFILE_ID,
    pref_field,
)


class LLMPreferences(BaseModel):
    """Which catalog models to use when the workspace has credentials for them."""

    default_chat: str | None = pref_field(
        model_kind="chat", default=None, title="Default chat model"
    )
    default_stt: str | None = pref_field(
        model_kind="stt", default=None, title="Default speech-to-text model"
    )
    default_tts: str | None = pref_field(
        model_kind="tts", default=None, title="Default text-to-speech model"
    )
    # Workspace-wide default cross-encoder reranker. Both the knowledge retrieval reranker
    # (knowledge.retrieval.reranker.model_id) and the graph fact-search reranker
    # (graph.reranker.model_id) fall back to this when their own model is empty — one place
    # to manage the reranker for both legs. Null = no default (each leg reranks only if it
    # sets its own model).
    default_reranker: str | None = pref_field(
        model_kind="rerank",
        default=None,
        title="Default reranker model",
        description=(
            "Default cross-encoder reranker. The knowledge and graph rerankers both fall "
            "back to this when their own model is empty. Empty = no default. Cloud models "
            "need a provider key; local models must be downloaded first."
        ),
    )
    # Workspace-wide default embedder. The knowledge embedder (knowledge.default_embedding_model)
    # and the graph embedder (graph.embedder_model) both fall back to this when their own model is
    # empty. NOT forced to any model: null = no default, and indexing is blocked until an embedder
    # is chosen (embedding is mandatory + dimension-bound, so there is no silent fallback). Never
    # locked — it only seeds consumers that have not indexed yet.
    default_embedder: str | None = pref_field(
        model_kind="embedding",
        default=None,
        title="Default embedder model",
        description=(
            "Default embedder. The knowledge and graph embedders both fall back to this when "
            "their own model is empty. Empty = no default (indexing is blocked until one is "
            "chosen). Cloud models need a provider key; local models must be downloaded first."
        ),
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
    # One timeout + retry policy for every cloud model call (chat, STT, TTS) on every provider.
    # Before this, each SDK used its own: Gemini had NO timeout and 6 attempts (plus 4 more in our
    # STT/TTS wrappers), so a Gemini 503 spell on 2026-11-06 left a chat turn waiting minutes.
    # Applied in model_factory (chat) and the STT/TTS builders via model_http.ProviderCallPolicy.
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
            "streamed answer) before that attempt counts as failed. Applies to chat, "
            "speech-to-text and text-to-speech on every cloud provider. Takes effect on server "
            "restart."
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
    default_tuning_profile: str = pref_field(
        tuning_profile_ref=True,
        default=DEFAULT_CHAT_TUNING_PROFILE_ID,
        title="Default chat model profile",
    )
    default_image_profile: str = pref_field(
        save_skip=True,
        default=DEFAULT_IMAGE_PLAYGROUND_PROFILE_ID,
    )
