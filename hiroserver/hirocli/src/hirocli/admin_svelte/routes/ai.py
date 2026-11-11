"""AI profile and use routes (Phase 7a) — the Catalog's AI tabs over the AI tools (tools/ai.py).

Profiles are created, changed and deleted through the preferences API (``ai.profiles.<id>``, like
``image_profiles``); these routes read them (with Hiro's own jobs, Phase 7b step 5), restore a job's
default profile to its preset tuning, Try one, manage ``ai.uses``, refresh the uses
connected extensions declare (the running server's ExtensionManager) and check a local server's
models. Part B adds the plan tools (``/ai/plans/...``: status, sign-in, sign-out, test, update) and the
local servers' status and settings (``/ai/local-servers``).
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import api_failure
from hirocli.admin_svelte.routes.extensions import _live_manager
from hirocli.domain.discovered_models import DISCOVERABLE_LOCAL_PROVIDERS, list_discovered_models
from hirocli.domain.workspace import WorkspaceError, resolve_workspace
from hirocli.runtime.preferences_runtime import PreferencePathError
from hirocli.tools.ai import (
    AiProfileRestoreDefaultTool,
    AiProfilesListTool,
    AiTryTool,
    AiUsageTool,
    AiUsesForgetTool,
    AiUsesListTool,
    AiUsesSetTool,
    LocalServerCheckTool,
    LocalServerSetTool,
    refresh_extension_uses,
)
from hirocli.tools.ai_plans import PlanSignInTool, PlanSignOutTool, PlanStatusTool, PlanTestTool, PlanUpdateTool
from hirocli.services.plans.cli import PlanToolError

ai_router = APIRouter()


class AiTryBody(BaseModel):
    prompt: str
    profile_id: str | None = None
    draft: dict[str, Any] | None = None  # a profile not saved yet (AI profile fields)
    picture: str | None = None  # base64 JPEG (a data: URL is fine)
    # "schema" on the wire; a field named schema would shadow BaseModel's own attribute.
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")

    model_config = {"populate_by_name": True}


class AiUseBody(BaseModel):
    profile_id: str | None = None


class AiRefreshBody(BaseModel):
    extension_id: str | None = None


class LocalServerCheckBody(BaseModel):
    base_url: str | None = None


def _ok(data: Any) -> Any:
    return data


def _workspace_path(workspace_id: str | None) -> Path | None:
    if not workspace_id:
        return None
    try:
        entry, _ = resolve_workspace(workspace_id)
    except WorkspaceError:
        return None
    return Path(entry.path)


@ai_router.get("/ai/profiles")
async def ai_profiles(workspace_id: SelectedWorkspaceIdDep) -> Any:
    if not workspace_id:
        return api_failure("No workspace selected.")
    try:
        result = await run_in_threadpool(AiProfilesListTool().execute, workspace=workspace_id)
    except (WorkspaceError, ValueError, OSError) as exc:
        return api_failure(str(exc))
    return _ok(asdict(result))


@ai_router.post("/ai/profiles/{profile_id}/restore-default")
async def ai_profile_restore_default(profile_id: str, workspace_id: SelectedWorkspaceIdDep) -> Any:
    """Phase 7b step 5: a job's default AI profile back to its preset tuning (model kept)."""
    if not workspace_id:
        return api_failure("No workspace selected.")
    try:
        result = await run_in_threadpool(
            AiProfileRestoreDefaultTool().execute, profile_id=profile_id, workspace=workspace_id
        )
    except (ValidationError, PreferencePathError, ValueError, WorkspaceError) as exc:
        return api_failure(str(exc))
    return _ok(asdict(result))


@ai_router.get("/ai/local-models")
async def ai_local_models(workspace_id: SelectedWorkspaceIdDep) -> Any:
    """The models local servers last reported (offered as lm_studio:<name> / ollama:<name>)."""
    path = _workspace_path(workspace_id)
    if path is None:
        return api_failure("No workspace selected.")
    models = await run_in_threadpool(list_discovered_models, path)
    return _ok({"models": [{**asdict(m), "id": m.id} for m in models]})


@ai_router.post("/ai/try")
async def ai_try(body: AiTryBody, workspace_id: SelectedWorkspaceIdDep) -> Any:
    """Try it: one ask on a saved or draft profile (async — runs on the server loop like ai.ask)."""
    if not workspace_id:
        return api_failure("No workspace selected.")
    try:
        result = await AiTryTool().execute_async(
            prompt=body.prompt,
            profile_id=body.profile_id,
            draft=body.draft,
            picture=body.picture,
            schema=body.schema_,
            workspace=workspace_id,
        )
    except (WorkspaceError, ValueError) as exc:
        return api_failure(str(exc))
    return _ok(asdict(result))


@ai_router.get("/ai/usage")
async def ai_usage(workspace_id: SelectedWorkspaceIdDep, start: str, end: str) -> Any:
    """Phase 7b: Logs → AI usage — every paid AI call per hour in [start, end) (ISO date-times)."""
    if _workspace_path(workspace_id) is None:
        return api_failure("No workspace selected.")
    try:
        result = await run_in_threadpool(AiUsageTool().execute, start=start, end=end, workspace=workspace_id)
    except (WorkspaceError, ValueError, OSError) as exc:
        return api_failure(str(exc))
    return _ok(asdict(result))


@ai_router.get("/ai/uses")
async def ai_uses(request: Request, workspace_id: SelectedWorkspaceIdDep) -> Any:
    path = _workspace_path(workspace_id)
    if path is None:
        return api_failure("No workspace selected.")
    try:
        result = await run_in_threadpool(AiUsesListTool().execute, workspace=workspace_id)
    except (WorkspaceError, ValueError, OSError) as exc:
        return api_failure(str(exc))
    manager = _live_manager(request, path)
    connected = set(manager.snapshot()) if manager is not None else None
    extensions = [
        {**ext, "connected": (ext["extension_id"] in connected) if connected is not None and ext["extension_id"] else False}
        for ext in result.extensions
    ]
    return _ok({"extensions": extensions, "live": manager is not None})


@ai_router.put("/ai/uses/{key}")
async def ai_use_set(key: str, body: AiUseBody, workspace_id: SelectedWorkspaceIdDep) -> Any:
    if not workspace_id:
        return api_failure("No workspace selected.")
    try:
        result = await run_in_threadpool(
            AiUsesSetTool().execute, key=key, profile_id=body.profile_id, workspace=workspace_id
        )
    except (ValidationError, PreferencePathError, ValueError, WorkspaceError) as exc:
        return api_failure(str(exc))
    return _ok(asdict(result))


@ai_router.delete("/ai/uses/{key}")
async def ai_use_forget(key: str, workspace_id: SelectedWorkspaceIdDep) -> Any:
    if not workspace_id:
        return api_failure("No workspace selected.")
    try:
        result = await run_in_threadpool(AiUsesForgetTool().execute, key=key, workspace=workspace_id)
    except (ValidationError, PreferencePathError, ValueError, WorkspaceError) as exc:
        return api_failure(str(exc))
    return _ok(asdict(result))


@ai_router.post("/ai/uses/refresh")
async def ai_uses_refresh(body: AiRefreshBody, request: Request, workspace_id: SelectedWorkspaceIdDep) -> Any:
    """Ask connected extensions for their uses again (the Uses tab's Refresh)."""
    path = _workspace_path(workspace_id)
    if path is None:
        return api_failure("No workspace selected.")
    manager = _live_manager(request, path)
    if manager is None:
        return api_failure("The server for this workspace isn't running here.")
    result = await refresh_extension_uses(manager, body.extension_id)
    return _ok(asdict(result))


@ai_router.post("/ai/local-servers/{provider_id}/check")
async def ai_local_server_check(
    provider_id: str, body: LocalServerCheckBody, workspace_id: SelectedWorkspaceIdDep
) -> Any:
    if not workspace_id:
        return api_failure("No workspace selected.")
    try:
        result = await run_in_threadpool(
            LocalServerCheckTool().execute, provider_id=provider_id, base_url=body.base_url, workspace=workspace_id
        )
    except (ValueError, WorkspaceError, OSError) as exc:
        return api_failure(str(exc))
    return _ok(asdict(result))


# ---------------------------------------------------------------------------
# Part B: plan tools (Claude Code / Codex) and local servers' status and settings
# ---------------------------------------------------------------------------


class PlanSignInBody(BaseModel):
    action: str = "start"  # start | state | code | cancel
    code: str | None = None


class PlanUpdateBody(BaseModel):
    wait: bool = False  # npm can take minutes: the admin polls GET /ai/plans


class LocalServerSetBody(BaseModel):
    base_url: str | None = None
    unload_idle_min: int | None = None
    context: int | None = None
    batch: int | None = None


async def _run_tool(fn: Any, **kwargs: Any) -> Any:
    """A blocking tool in a worker thread, its result in the envelope; expected failures as ok: false."""
    try:
        result = await run_in_threadpool(fn, **kwargs)
    except (PlanToolError, ValidationError, PreferencePathError, ValueError, WorkspaceError, OSError) as exc:
        return api_failure(str(exc))
    return _ok(asdict(result))


@ai_router.get("/ai/plans")
async def ai_plans(workspace_id: SelectedWorkspaceIdDep, fresh: bool = False) -> Any:
    if not workspace_id:
        return api_failure("No workspace selected.")
    return await _run_tool(PlanStatusTool().execute, fresh=fresh, workspace=workspace_id)


@ai_router.post("/ai/plans/{tool}/sign-in")
async def ai_plan_sign_in(tool: str, body: PlanSignInBody, workspace_id: SelectedWorkspaceIdDep) -> Any:
    """Start / poll / paste the code / cancel. The sign-in's program runs in this (the server's) process."""
    if not workspace_id:
        return api_failure("No workspace selected.")
    return await _run_tool(PlanSignInTool().execute, tool=tool, action=body.action, code=body.code, workspace=workspace_id)


@ai_router.post("/ai/plans/{tool}/sign-out")
async def ai_plan_sign_out(tool: str, workspace_id: SelectedWorkspaceIdDep) -> Any:
    if not workspace_id:
        return api_failure("No workspace selected.")
    return await _run_tool(PlanSignOutTool().execute, tool=tool, workspace=workspace_id)


@ai_router.post("/ai/plans/{tool}/test")
async def ai_plan_test(tool: str, workspace_id: SelectedWorkspaceIdDep) -> Any:
    if not workspace_id:
        return api_failure("No workspace selected.")
    return await _run_tool(PlanTestTool().execute, tool=tool, workspace=workspace_id)


@ai_router.post("/ai/plans/update")
async def ai_plans_update(body: PlanUpdateBody, workspace_id: SelectedWorkspaceIdDep) -> Any:
    if not workspace_id:
        return api_failure("No workspace selected.")
    return await _run_tool(PlanUpdateTool().execute, wait=body.wait, workspace=workspace_id)


@ai_router.get("/ai/local-servers")
async def ai_local_servers(workspace_id: SelectedWorkspaceIdDep) -> Any:
    """Both local server kinds, checked now (up/down, models, loaded, settings)."""
    if not workspace_id:
        return api_failure("No workspace selected.")
    # Checked side by side: a server whose machine is off waits out the list timeout (5 s), and
    # one after the other the page waited for both.
    results = await asyncio.gather(
        *(
            _run_tool(LocalServerCheckTool().execute, provider_id=pid, workspace=workspace_id)
            for pid in DISCOVERABLE_LOCAL_PROVIDERS
        )
    )
    # Step 1d fix: _run_tool answers the data itself or the failure response; there is no
    # {"ok", "data"} envelope to read (this route raised KeyError 'ok', an HTTP 500).
    for one in results:
        if isinstance(one, Response):
            return one
    return _ok({"servers": list(results)})


@ai_router.put("/ai/local-servers/{provider_id}")
async def ai_local_server_set(
    provider_id: str, body: LocalServerSetBody, workspace_id: SelectedWorkspaceIdDep
) -> Any:
    if not workspace_id:
        return api_failure("No workspace selected.")
    return await _run_tool(
        LocalServerSetTool().execute,
        provider_id=provider_id,
        base_url=body.base_url,
        unload_idle_min=body.unload_idle_min,
        context=body.context,
        batch=body.batch,
        workspace=workspace_id,
    )
