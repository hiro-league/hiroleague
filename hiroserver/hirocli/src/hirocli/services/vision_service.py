"""VisionService — image understanding via a LangChain multimodal vision model.

Model: the "Reading pictures" job's AI profile (``llm.vision_profile``, Phase 7b step 5 — it replaced
the ``IMAGE_VISION_MODEL`` env var and the hard-coded 0.7 / 4096 tuning). No profile → vision is off
(logged once). Default prompt: generic description (override with ``IMAGE_ANALYSIS_PROMPT`` env var).

The model is built via ``create_chat_model()`` from the resolved profile (its fallback chain walked,
first available model wins); it is rebuilt when the resolved profile changes.

Two interfaces:
  - async describe(source, prompt?)  — for the adapter pipeline and async callers
  - describe_sync(source, prompt?)   — for tools and other sync callers
"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

log = Logger.get("SVC.VISION")

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
        self._model_key: tuple[Any, ...] | None = None
        self._credential_store = None  # Lazily built when workspace_path is set (avoids repeated disk reads).
        self._off_logged = False

    def invalidate_workspace_credentials(self) -> None:
        """Drop cached credential store and vision model after ``providers.json`` / keyring changes."""
        self._credential_store = None
        self._model = None
        self._model_key = None

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

    def _resolved(self):
        """The vision job's resolved model (``resolve_job_model(..., "vision")``), or None = off."""
        if self._workspace_path is None:
            return None
        pair = self._workspace_credential_store()
        if pair is None:
            return None
        from ..domain.preferences import resolve_job_model
        from ..runtime.preferences_runtime import preferences_runtime_for

        store, wid = pair
        prefs = preferences_runtime_for(self._workspace_path).current
        resolved = resolve_job_model(prefs, self._workspace_path, "vision", workspace_id=wid, credential_store=store)
        if resolved is None and not self._off_logged:
            self._off_logged = True
            log.info("Reading pictures is off — no AI profile for it (llm.vision_profile) or its model isn't available")
        elif resolved is not None:
            self._off_logged = False
        return resolved

    def is_available(self) -> bool:
        """Return True when the vision job's AI profile resolves to a model that can run now."""
        return self._resolved() is not None

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
        resolved = self._resolved()
        if resolved is None:
            raise RuntimeError(
                "Reading pictures is off: pick an AI profile for it (Preferences, llm.vision_profile) "
                "whose provider is set up."
            )
        key = (resolved.profile_id, resolved.model_id, resolved.temperature, resolved.max_tokens,
               resolved.thinking, resolved.num_ctx)
        if self._model is None or key != self._model_key:
            from ..domain.model_factory import create_chat_model

            store, wid = self._workspace_credential_store()  # type: ignore[misc]  # _resolved checked it
            try:
                self._model = create_chat_model(
                    resolved.model_id,
                    workspace_path=self._workspace_path,  # type: ignore[arg-type]
                    workspace_id=wid,
                    temperature=resolved.temperature,
                    max_tokens=resolved.max_tokens,
                    thinking=resolved.thinking,
                    num_ctx=resolved.num_ctx,
                    credential_store=store,
                )
            except ValueError as exc:
                raise RuntimeError(
                    f"Vision model {resolved.model_id!r} (AI profile {resolved.profile_id!r}) cannot be "
                    f"built for this workspace: {exc}"
                ) from exc
            self._model_key = key
        return self._model


def _resolve_image_url(source: str) -> str:
    """Return a URL or data URI suitable for the vision API."""
    if source.startswith("data:") or source.startswith("http"):
        return source
    return f"data:image/jpeg;base64,{source}"
