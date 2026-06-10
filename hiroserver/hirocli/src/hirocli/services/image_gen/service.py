"""ImageGenService — model-centric text-to-image orchestrator.

Aggregates ImageGenProvider instances behind one interface; callers think in model
ids and the provider is resolved automatically. Mirrors ``TTSService``.

Configuration
-------------
    The default image model is resolved from ``preferences.llm.default_image_gen``
    (a canonical catalog id) through the catalog + credential store by
    ``create_image_gen_service``. The service itself does not read config files;
    profile scaffolding (style prefix/suffix) is applied by callers before generate().
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from hiro_commons.log import Logger

from .provider import ImageGenModelInfo, ImageGenProvider, ImageGenResult

log = Logger.get("IMAGEGEN.SERVICE")


class ImageGenService:
    """Model-centric image-generation service.

    Each provider is asked whether it is available at construction; unavailable
    providers (missing token/account id) are silently skipped — same contract
    as TTSService.
    """

    def __init__(
        self,
        providers: list[ImageGenProvider] | None = None,
        default_model: str | None = None,
    ) -> None:
        self.providers: list[ImageGenProvider] = []
        self._model_to_provider: dict[str, ImageGenProvider] = {}
        self._models: list[ImageGenModelInfo] = []

        for provider in (providers or []):
            if not provider.is_available():
                log.debug("Image-gen provider not available, skipping", provider=provider.name)
                continue
            self.providers.append(provider)
            for model_info in provider.supported_models():
                self._model_to_provider[model_info.model_id] = provider
                self._models.append(model_info)
            log.info(
                f"✅ Image-gen provider loaded: {provider.name}",
                models=[m.model_id for m in provider.supported_models()],
            )

        if default_model and default_model in self._model_to_provider:
            self._default_model: str | None = default_model
        elif self._models:
            self._default_model = self._models[0].model_id
        else:
            self._default_model = None

        if self._default_model:
            log.info(f"👍 Image-gen default model: {self._default_model}")
        else:
            log.warning("No image-gen providers available — generation disabled")

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """True when at least one provider is loaded."""
        return bool(self._model_to_provider)

    def list_models(self) -> list[ImageGenModelInfo]:
        """All models from all available providers."""
        return list(self._models)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        steps: int = 4,
        size: str | None = None,
        seed: int | None = None,
        **kwargs: object,
    ) -> ImageGenResult:
        """Generate an image and return an ImageGenResult.

        ``model`` is a short catalog model id from list_models(); omitted → default.
        """
        if not prompt or not prompt.strip():
            raise ValueError("Image prompt is empty")

        effective_model = model or self._default_model
        if not effective_model:
            raise RuntimeError(
                "No image-generation providers are available. "
                "Configure a provider (e.g. cloudflare) and set llm.default_image_gen "
                "in preferences."
            )

        provider = self._model_to_provider.get(effective_model)
        if provider is None:
            available = [m.model_id for m in self._models]
            raise ValueError(
                f"Unknown image model {effective_model!r}. Available: {available}"
            )

        log.info(
            "Image generation request",
            model=effective_model,
            provider=provider.name,
            steps=steps,
            prompt_len=len(prompt),
        )
        result = await provider.generate(
            prompt, model=effective_model, steps=steps, size=size, seed=seed, **kwargs,
        )
        log.info(
            "Image generation result",
            model=effective_model,
            image_bytes=len(result.image_bytes),
            mime_type=result.mime_type,
            elapsed_ms=result.elapsed_ms,
        )
        return result

    def generate_sync(self, prompt: str, **kwargs: object) -> ImageGenResult:
        """Synchronous wrapper — safe from a tool or non-async context.

        Runs generate() in a dedicated thread so an existing event loop in the
        calling thread is not affected (same pattern as TTSService.synthesize_sync).
        """
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(asyncio.run, self.generate(prompt, **kwargs))
            return future.result()
