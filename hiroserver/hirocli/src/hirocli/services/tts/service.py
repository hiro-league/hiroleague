"""TTSService — model-centric text-to-speech orchestrator.

Aggregates multiple TTSProvider instances into a single interface. Callers
think in terms of model IDs; the provider is resolved automatically.

Usage
-----
    from hirocli.services.tts import TTSService, OpenAITTSProvider, GeminiTTSProvider

    tts = TTSService(providers=[OpenAITTSProvider(), GeminiTTSProvider()])

    # Async (agent post-processing, adapters):
    result = await tts.synthesize("Hello world")
    result = await tts.synthesize("Hello", model="gpt-4o-mini-tts", voice="sage")

    # Sync (CLI tools):
    result = tts.synthesize_sync("Hello world")

    # Introspection:
    for m in tts.list_models():
        print(m.model_id, m.display_name)

Configuration
-------------
    The default TTS model is resolved from preferences.json via resolve_voice().
    Callers that construct TTSService pass default_model explicitly;
    the service itself does not read env vars or config files.

    OPENAI_API_KEY        Enables OpenAITTSProvider.
    GOOGLE_API_KEY /
    GEMINI_API_KEY        Enables GeminiTTSProvider.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from hiro_commons.log import Logger

from .provider import TTSModelInfo, TTSProvider, TTSResult

log = Logger.get("TTS.SERVICE")


class TTSService:
    """Model-centric text-to-speech service.

    On construction, each provider is asked whether it is available.
    Only available providers contribute models to the registry. Unavailable
    providers (missing API key, missing SDK) are silently skipped.
    """

    def __init__(
        self,
        providers: list[TTSProvider] | None = None,
        default_model: str | None = None,
    ) -> None:
        self._model_to_provider: dict[str, TTSProvider] = {}
        self._models: list[TTSModelInfo] = []

        for provider in (providers or []):
            if not provider.is_available():
                log.debug("TTS provider not available, skipping", provider=provider.name)
                continue
            for model_info in provider.supported_models():
                self._model_to_provider[model_info.model_id] = provider
                self._models.append(model_info)
            log.info(
                f"✅ TTS provider loaded: {provider.name}",
                models=[m.model_id for m in provider.supported_models()],
            )

        if default_model and default_model in self._model_to_provider:
            self._default_model: str | None = default_model
        elif self._models:
            self._default_model = self._models[0].model_id
        else:
            self._default_model = None

        if self._default_model:
            log.info(f"TTS default model: {self._default_model}")
        else:
            log.warning("No TTS providers available — synthesis disabled")

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True when at least one provider is loaded."""
        return bool(self._model_to_provider)

    def list_models(self) -> list[TTSModelInfo]:
        """Return all models from all available providers."""
        return list(self._models)

    # ------------------------------------------------------------------
    # Synthesis
    # ------------------------------------------------------------------

    async def synthesize(
        self,
        text: str,
        *,
        model: str | None = None,
        voice: str = "",
        instructions: str = "",
        **kwargs: object,
    ) -> TTSResult:
        """Synthesize speech from text and return a TTSResult.

        ``model`` selects a specific model (must be one from list_models()).
        When omitted, the default model is used.

        ``voice`` and ``instructions`` are forwarded to the provider.

        Extra keyword arguments are forwarded to the provider.
        """
        if not text:
            raise ValueError("Text to synthesize is empty")

        effective_model = model or self._default_model
        if not effective_model:
            raise RuntimeError(
                "No TTS providers are available. "
                "Set OPENAI_API_KEY or GOOGLE_API_KEY to enable speech synthesis."
            )

        provider = self._model_to_provider.get(effective_model)
        if provider is None:
            available = [m.model_id for m in self._models]
            raise ValueError(
                f"Unknown TTS model {effective_model!r}. "
                f"Available: {available}"
            )

        log.info(
            "Synthesize request",
            model=effective_model,
            provider=provider.name,
            text_len=len(text),
            voice=voice,
        )
        result = await provider.synthesize(
            text, model=effective_model, voice=voice,
            instructions=instructions, **kwargs,
        )
        log.info(
            "Synthesize result",
            model=effective_model,
            audio_bytes=len(result.audio_bytes),
            duration_ms=result.duration_ms,
            mime_type=result.mime_type,
        )
        return result

    def synthesize_sync(self, text: str, **kwargs: object) -> TTSResult:
        """Synchronous wrapper — safe to call from a tool or non-async context.

        Runs synthesize() in a dedicated thread so an existing event loop in
        the calling thread is not affected.
        """
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(asyncio.run, self.synthesize(text, **kwargs))
            return future.result()
