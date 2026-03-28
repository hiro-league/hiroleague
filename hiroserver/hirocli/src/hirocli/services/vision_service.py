"""VisionService — image understanding via a LangChain multimodal vision model.

Default model: ``openai:gpt-4o-mini`` (override with ``IMAGE_VISION_MODEL`` env var).
Default prompt: generic description (override with ``IMAGE_ANALYSIS_PROMPT`` env var).

With ``workspace_path``, the vision model is built via ``create_chat_model()`` and
availability follows the workspace credential store. Without a workspace (legacy
callers), availability falls back to ``OPENAI_API_KEY`` in the environment.

Two interfaces:
  - async describe(source, prompt?)  — for the adapter pipeline and async callers
  - describe_sync(source, prompt?)   — for tools and other sync callers
"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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

    def __init__(self, workspace_path: Path | None = None) -> None:
        self._workspace_path = workspace_path
        self._model = None
        self._credential_store = None  # Lazily built when workspace_path is set (avoids repeated disk reads).

    def _workspace_credential_store(self):
        """Return ``(store, workspace_id)`` or None if workspace is not registry-backed."""
        if self._workspace_path is None:
            return None
        from ..domain.credential_store import CredentialStore
        from ..domain.workspace import workspace_id_for_path

        wid = workspace_id_for_path(self._workspace_path)
        if wid is None:
            return None
        if self._credential_store is None:
            self._credential_store = CredentialStore(self._workspace_path, wid)
        return self._credential_store, wid

    def is_available(self) -> bool:
        """Return True when the configured vision model can run in this context."""
        model_id = os.environ.get("IMAGE_VISION_MODEL", _DEFAULT_MODEL)
        if self._workspace_path is not None:
            from ..domain.model_catalog import get_model_catalog

            spec = get_model_catalog().get_model(model_id)
            if spec is None or spec.model_kind != "chat":
                return False
            pair = self._workspace_credential_store()
            if pair is None:
                return False
            store, _wid = pair
            return store.is_configured(spec.provider_id)
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
            model_id = os.environ.get("IMAGE_VISION_MODEL", _DEFAULT_MODEL)
            if self._workspace_path is not None:
                from ..domain.model_factory import create_chat_model

                try:
                    self._model = create_chat_model(
                        model_id,
                        workspace_path=self._workspace_path,
                        temperature=0.7,
                        max_tokens=4096,
                    )
                except ValueError as exc:
                    raise RuntimeError(
                        f"Vision model {model_id!r} cannot be built for this workspace "
                        f"(check IMAGE_VISION_MODEL and provider credentials): {exc}"
                    ) from exc
            else:
                from langchain.chat_models import init_chat_model

                try:
                    self._model = init_chat_model(model_id)
                except ValueError as exc:
                    raise RuntimeError(
                        f"Vision model {model_id!r} is invalid for env-based init: {exc}"
                    ) from exc
        return self._model


def _resolve_image_url(source: str) -> str:
    """Return a URL or data URI suitable for the vision API."""
    if source.startswith("data:") or source.startswith("http"):
        return source
    return f"data:image/jpeg;base64,{source}"
