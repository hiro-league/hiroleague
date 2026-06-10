"""Image Lab routes (workspace-scoped) — playground over the generate_image tool."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from hirocli.admin.features.image_lab.service import ImageLabService
from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import _api_from_result
from hirocli.admin_svelte.schemas import ImageLabGenerateRequest
from hirocli.tools.image_gen import GenerateImageTool

image_lab_router = APIRouter()


@image_lab_router.get("/image-lab/options")
async def image_lab_options(workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    result = await run_in_threadpool(ImageLabService().options, workspace_id)
    return _api_from_result(result)


@image_lab_router.post("/image-lab/generate")
async def image_lab_generate(
    body: ImageLabGenerateRequest,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    """Generate one image via the shared generate_image tool (async — no thread hop)."""
    if not workspace_id:
        return {"ok": False, "error": "No workspace selected.", "data": None}
    try:
        result = await GenerateImageTool().execute_async(
            prompt=body.prompt,
            profile=body.profile_id,
            model=body.model,
            steps=body.steps,
            seed=body.seed,
            workspace=workspace_id,
        )
        return {"ok": True, "error": None, "data": asdict(result)}
    except (ValueError, RuntimeError) as exc:
        return {"ok": False, "error": str(exc), "data": None}
