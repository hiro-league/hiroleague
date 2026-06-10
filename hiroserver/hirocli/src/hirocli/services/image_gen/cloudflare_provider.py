"""Cloudflare Workers AI image generation — FLUX.1 [schnell] via the REST run endpoint.

API contract (developers.cloudflare.com/workers-ai/models/flux-1-schnell, verified 2026-06):
  POST https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/black-forest-labs/flux-1-schnell
  Authorization: Bearer <api_token>
  Body: {"prompt": <1-2048 chars>, "steps": <1-8, default 4>, "seed": <optional int>}
  Response: JSON with a base64-encoded JPEG, fixed 1024x1024 (no width/height params).
  The REST wrapper nests the model output under "result"; both shapes are handled.

Credentials come from the workspace credential store: the API token is the keyring
secret, the account id is non-secret providers.json metadata (it is part of the URL).
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any

import httpx
from hiro_commons.log import Logger

from .provider import ImageGenModelInfo, ImageGenProvider, ImageGenResult

log = Logger.get("IMAGEGEN.CLOUDFLARE")

_API_URL_TEMPLATE = (
    "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{api_model}"
)

_DEFAULT_MODEL = "flux-1-schnell"
_MAX_PROMPT_CHARS = 2048
_MIN_STEPS, _MAX_STEPS = 1, 8
_REQUEST_TIMEOUT_S = 90.0
# Transient failures (429 / 5xx / timeouts) get a short retry ladder; anything else fails fast.
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_S = (1.0, 2.0)

_MODELS: list[ImageGenModelInfo] = [
    ImageGenModelInfo(
        model_id="flux-1-schnell",
        provider="cloudflare",
        display_name="FLUX.1 [schnell]",
    ),
]

# Short model id → Workers AI model path used in the REST URL.
_API_MODEL_BY_ID: dict[str, str] = {
    "flux-1-schnell": "@cf/black-forest-labs/flux-1-schnell",
}


class CloudflareImageGenError(RuntimeError):
    """Cloudflare Workers AI returned an error or an unusable response."""


def _clamp_steps(steps: int) -> int:
    return max(_MIN_STEPS, min(_MAX_STEPS, int(steps)))


def _extract_image_b64(payload: dict[str, Any]) -> str | None:
    """Image field from either the raw model schema or the REST ``result`` wrapper."""
    node = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    image = node.get("image") if isinstance(node, dict) else None
    return image if isinstance(image, str) and image else None


def _error_summary(payload: dict[str, Any], status_code: int) -> str:
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        return "; ".join(str(e.get("message", e)) for e in errors if e)[:500]
    return f"HTTP {status_code}"


class CloudflareImageGenProvider(ImageGenProvider):
    """Text-to-image via the Cloudflare Workers AI REST run endpoint."""

    def __init__(self, *, api_token: str | None = None, account_id: str | None = None) -> None:
        self._api_token = api_token
        self._account_id = account_id

    @property
    def name(self) -> str:
        return "cloudflare"

    def is_available(self) -> bool:
        return bool(self._api_token) and bool(self._account_id)

    def supported_models(self) -> list[ImageGenModelInfo]:
        return list(_MODELS)

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
        text = (prompt or "").strip()
        if not text:
            raise ValueError("Image prompt is empty")
        if len(text) > _MAX_PROMPT_CHARS:
            raise ValueError(
                f"Image prompt is {len(text)} chars — Cloudflare flux-1-schnell allows "
                f"at most {_MAX_PROMPT_CHARS}"
            )

        effective_model = model or _DEFAULT_MODEL
        api_model = _API_MODEL_BY_ID.get(effective_model)
        if api_model is None:
            raise ValueError(
                f"Unknown Cloudflare image model {effective_model!r}. "
                f"Available: {sorted(_API_MODEL_BY_ID)}"
            )
        effective_steps = _clamp_steps(steps)
        if size:
            # flux-1-schnell has no width/height params — output is fixed 1024x1024.
            log.debug("Size hint ignored (fixed-resolution model)", size=size)

        url = _API_URL_TEMPLATE.format(account_id=self._account_id, api_model=api_model)
        body: dict[str, Any] = {"prompt": text, "steps": effective_steps}
        if seed is not None:
            body["seed"] = int(seed)
        headers = {"Authorization": f"Bearer {self._api_token}"}

        log.info(
            "⬆️ Image generation request — Cloudflare · flux",
            model=effective_model,
            steps=effective_steps,
            prompt_len=len(text),
            has_seed=seed is not None,
        )

        t0 = time.perf_counter()
        payload = await self._post_with_retries(url, headers, body)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        image_b64 = _extract_image_b64(payload)
        if image_b64 is None:
            summary = _error_summary(payload, 200)
            log.error(
                "❌ Image generation failed — Cloudflare · no image in response",
                error=summary,
                elapsed_ms=elapsed_ms,
                model=effective_model,
            )
            raise CloudflareImageGenError(f"Cloudflare returned no image: {summary}")

        try:
            image_bytes = base64.b64decode(image_b64)
        except Exception as exc:
            raise CloudflareImageGenError("Cloudflare returned undecodable image data") from exc

        log.info(
            "✅ Image generated — Cloudflare · flux",
            model=effective_model,
            steps=effective_steps,
            image_bytes=len(image_bytes),
            elapsed_ms=elapsed_ms,
        )
        return ImageGenResult(
            image_bytes=image_bytes,
            mime_type="image/jpeg",
            model=effective_model,
            provider=self.name,
            steps=effective_steps,
            seed=seed,
            width=1024,
            height=1024,
            elapsed_ms=elapsed_ms,
        )

    async def _post_with_retries(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """POST with a short retry ladder on transient failures (429/5xx/timeouts)."""
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    resp = await client.post(url, headers=headers, json=body)
                except httpx.TimeoutException as exc:
                    last_error = exc
                    log.warning(
                        "⚠️ Image generation timeout — Cloudflare · retrying",
                        attempt=attempt,
                        error=str(exc),
                    )
                except httpx.HTTPError as exc:
                    # Connection-level failure: not retryable in a way that helps interactivity.
                    log.error(
                        "❌ Image generation transport error — Cloudflare",
                        error=str(exc),
                        exc_info=True,
                    )
                    raise CloudflareImageGenError(
                        f"Could not reach Cloudflare Workers AI: {exc}"
                    ) from exc
                else:
                    if resp.status_code in (429,) or resp.status_code >= 500:
                        last_error = CloudflareImageGenError(
                            f"Cloudflare transient error: HTTP {resp.status_code}"
                        )
                        log.warning(
                            "⚠️ Image generation transient HTTP error — Cloudflare · retrying",
                            status=resp.status_code,
                            attempt=attempt,
                        )
                    else:
                        try:
                            payload: dict[str, Any] = resp.json()
                        except ValueError as exc:
                            raise CloudflareImageGenError(
                                f"Cloudflare returned non-JSON response (HTTP {resp.status_code})"
                            ) from exc
                        if resp.status_code >= 400 or payload.get("success") is False:
                            summary = _error_summary(payload, resp.status_code)
                            log.error(
                                "❌ Image generation rejected — Cloudflare",
                                status=resp.status_code,
                                error=summary,
                            )
                            raise CloudflareImageGenError(
                                f"Cloudflare image generation failed: {summary}"
                            )
                        return payload
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(_RETRY_BACKOFF_S[min(attempt - 1, len(_RETRY_BACKOFF_S) - 1)])
        raise CloudflareImageGenError(
            f"Cloudflare image generation failed after {_MAX_ATTEMPTS} attempts: {last_error}"
        ) from last_error
