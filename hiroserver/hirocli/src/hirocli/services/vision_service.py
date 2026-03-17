"""VisionService — image understanding via a LangChain multimodal vision model.

Default provider: OpenAI gpt-4o-mini (override with IMAGE_VISION_MODEL env var).
Default prompt: generic description (override with IMAGE_ANALYSIS_PROMPT env var).
The service is disabled when OPENAI_API_KEY is not set.

Two interfaces:
  - async describe(source, prompt?)  — for the adapter pipeline and async callers
  - describe_sync(source, prompt?)   — for tools and other sync callers
"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

from hiro_commons.log import Logger

log = Logger.get("SVC.VISION")

_DEFAULT_MODEL = "openai:gpt-4o-mini"

_DEFAULT_PROMPT = (
    "Describe this image concisely. Focus on the main subject, key details, "
    "and anything that would be useful context for a text-based assistant."
)


class VisionService:
    """Describes an image from a URL, data URI, or raw base64 string.

    LangChain model resources are lazy-initialised on first use.
    """

    def __init__(self) -> None:
        self._model = None

    def is_available(self) -> bool:
        """Return True when a supported provider API key is configured."""
        return bool(os.environ.get("OPENAI_API_KEY"))

    async def describe(self, source: str, prompt: str | None = None) -> str:
        """Describe the image and return a text description.

        ``source`` may be a URL, a data URI (``data:<mime>;base64,...``),
        or a raw base64-encoded image string (assumed JPEG).
        ``prompt`` overrides the default analysis prompt.
        """
        if not source:
            raise ValueError("Image source is empty")

        log.info("Analysing image")
        model = self._get_model()
        effective_prompt = (
            prompt
            or os.environ.get("IMAGE_ANALYSIS_PROMPT")
            or _DEFAULT_PROMPT
        )
        image_url = _resolve_image_url(source)

        from langchain_core.messages import HumanMessage

        message = HumanMessage(
            content=[
                {"type": "text", "text": effective_prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]
        )

        response = await model.ainvoke([message])
        description = response.content if isinstance(response.content, str) else str(response.content)
        log.info("Image analysis complete", chars=len(description))
        return description.strip()

    def describe_sync(self, source: str, prompt: str | None = None) -> str:
        """Synchronous wrapper — safe to call from a tool or non-async context.

        Runs the async describe() in a dedicated thread so an existing
        event loop in the calling thread is not affected.
        """
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(asyncio.run, self.describe(source, prompt))
            return future.result()

    def _get_model(self):
        if self._model is None:
            from langchain.chat_models import init_chat_model

            model_id = os.environ.get("IMAGE_VISION_MODEL", _DEFAULT_MODEL)
            self._model = init_chat_model(model_id)
        return self._model


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_image_url(source: str) -> str:
    """Return a URL or data URI suitable for the vision API."""
    if source.startswith("data:") or source.startswith("http"):
        return source
    return f"data:image/jpeg;base64,{source}"
