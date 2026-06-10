"""Image-generation tool — text-to-image via the workspace image-gen service.

Exposes the same capability to CLI, HTTP ``/invoke``, and (opt-in) the AI agent.
Profile resolution and prompt scaffolding follow the workspace ``image_profiles``
preferences; per-call params override the profile (resolution order: call params >
profile > ``llm.default_image_gen``).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..domain.workspace import WorkspaceError, resolve_workspace
from .base import Tool, ToolParam


def _image_workspace_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


@dataclass
class GenerateImageResult:
    """JSON-safe generation result (``/invoke`` serializes via asdict)."""

    image_base64: str
    mime_type: str
    model: str
    provider: str
    profile: str
    steps: int
    seed: int | None
    width: int | None
    height: int | None
    prompt_used: str
    elapsed_ms: int
    estimated_cost_usd: float | None

    def __str__(self) -> str:
        # Human/agent-facing summary — never the base64 payload.
        size = f"{self.width}x{self.height}" if self.width and self.height else "unknown size"
        cost = f", ~${self.estimated_cost_usd:.5f}" if self.estimated_cost_usd is not None else ""
        kb = len(self.image_base64) * 3 // 4 // 1024
        return (
            f"Generated {size} {self.mime_type} image ({kb} KB) with {self.model} "
            f"(profile={self.profile}, steps={self.steps}, {self.elapsed_ms} ms{cost})"
        )


class GenerateImageTool(Tool):
    """Generate an image from a text prompt using the configured image-gen provider."""

    name = "generate_image"
    description = (
        "Generate an image from a text prompt using the workspace image-generation "
        "model (e.g. Cloudflare FLUX.1 schnell). Optionally pick a named image profile "
        "(style scaffolding + params) or override model/steps/seed for this call."
    )
    # External paid call the model could trigger freely — agent-surfaced but opt-in only.
    agent_default = False
    params = {
        "prompt": ToolParam(str, "Text description of the image to generate"),
        "profile": ToolParam(
            str,
            "Image profile id from preferences.image_profiles "
            "(optional — defaults to llm.default_image_profile)",
            required=False,
        ),
        "model": ToolParam(
            str,
            "Canonical catalog model id, e.g. 'cloudflare:flux-1-schnell' "
            "(optional — defaults to the profile's model, then llm.default_image_gen)",
            required=False,
        ),
        "steps": ToolParam(
            int,
            "Diffusion steps (1-8 for flux-1-schnell; optional — defaults to the profile)",
            required=False,
        ),
        "seed": ToolParam(
            int,
            "Reproducibility seed (optional — random when omitted)",
            required=False,
        ),
        "workspace": ToolParam(
            str,
            "Workspace name (default: registry default); used for credentials and preferences",
            required=False,
        ),
    }

    def execute(self, **kwargs: Any) -> GenerateImageResult:
        """Sync path (CLI / threadpool dispatch) — runs the same resolution + call."""
        prompt: str = kwargs["prompt"]
        try:
            workspace_path = _image_workspace_path(kwargs.get("workspace"))
        except WorkspaceError as exc:
            raise RuntimeError(str(exc)) from exc

        service, resolved, final_prompt = _prepare(
            workspace_path,
            prompt=prompt,
            profile=kwargs.get("profile"),
            model=kwargs.get("model"),
            steps=kwargs.get("steps"),
            seed=kwargs.get("seed"),
        )
        result = service.generate_sync(
            final_prompt,
            model=resolved.model_id.split(":", 1)[1],
            steps=resolved.steps,
            size=resolved.size,
            seed=resolved.seed,
        )
        return _to_tool_result(result, resolved, final_prompt)

    async def execute_async(self, **kwargs: Any) -> GenerateImageResult:
        """Async path (HTTP /invoke, agent) — no thread hop for the HTTP call."""
        prompt: str = kwargs["prompt"]
        try:
            workspace_path = _image_workspace_path(kwargs.get("workspace"))
        except WorkspaceError as exc:
            raise RuntimeError(str(exc)) from exc

        service, resolved, final_prompt = _prepare(
            workspace_path,
            prompt=prompt,
            profile=kwargs.get("profile"),
            model=kwargs.get("model"),
            steps=kwargs.get("steps"),
            seed=kwargs.get("seed"),
        )
        result = await service.generate(
            final_prompt,
            model=resolved.model_id.split(":", 1)[1],
            steps=resolved.steps,
            size=resolved.size,
            seed=resolved.seed,
        )
        return _to_tool_result(result, resolved, final_prompt)


def _prepare(
    workspace_path: Path,
    *,
    prompt: str,
    profile: str | None,
    model: str | None,
    steps: int | None,
    seed: int | None,
):
    """Shared resolution: preferences profile + overrides → (service, resolved, final prompt)."""
    from ..domain.preferences import (
        compose_image_prompt,
        load_preferences,
        resolve_image_gen,
    )
    from ..services.image_gen import create_image_gen_service

    if not prompt or not prompt.strip():
        raise ValueError("prompt is required")

    prefs = load_preferences(workspace_path)
    resolved = resolve_image_gen(
        prefs,
        workspace_path,
        profile_id=profile,
        model_override=model,
        steps_override=int(steps) if steps is not None else None,
        seed_override=int(seed) if seed is not None else None,
    )
    if resolved is None:
        raise RuntimeError(
            "No image-generation model is available. Configure the provider "
            "(hiro provider add cloudflare, with account id) and set llm.default_image_gen "
            "in preferences — or pass an explicit model."
        )

    service = create_image_gen_service(workspace_path, prefs=prefs)
    if service is None or not service.is_available():
        raise RuntimeError(
            "Image-generation service unavailable for this workspace. "
            "Check the cloudflare API token and account id."
        )
    return service, resolved, compose_image_prompt(resolved, prompt)


def _to_tool_result(result, resolved, final_prompt: str) -> GenerateImageResult:
    from ..domain.model_catalog import get_model_catalog

    estimate = get_model_catalog().estimate_image_gen_cost(
        model_id=resolved.model_id, steps=result.steps,
    )
    return GenerateImageResult(
        image_base64=base64.b64encode(result.image_bytes).decode("ascii"),
        mime_type=result.mime_type,
        model=resolved.model_id,
        provider=result.provider,
        profile=resolved.profile_id,
        steps=result.steps,
        seed=result.seed,
        width=result.width,
        height=result.height,
        prompt_used=final_prompt,
        elapsed_ms=result.elapsed_ms,
        estimated_cost_usd=estimate.estimated_total if estimate.pricing_available else None,
    )
