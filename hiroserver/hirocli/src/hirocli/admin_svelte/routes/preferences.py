"""Workspace preferences routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import ValidationError

from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.schemas import PreferencesPatchRequest
from hirocli.domain.preferences import PREFERENCE_SECTIONS
from hirocli.domain.workspace import resolve_workspace
from hirocli.runtime.preferences_runtime import (
    PreferencePathError,
    WorkspacePreferencesRuntime,
)

preferences_router = APIRouter()


def _preferences_runtime(request: Request, workspace_id: str | None) -> WorkspacePreferencesRuntime:
    if not workspace_id:
        raise PreferencePathError("No workspace selected.")
    entry, _ = resolve_workspace(workspace_id)
    workspace_path = Path(entry.path)
    ctx = getattr(request.app.state, "ctx", None)
    runtime = getattr(ctx, "preferences", None) if ctx is not None else None
    ctx_workspace_path = getattr(ctx, "workspace_path", None) if ctx is not None else None
    if (
        runtime is not None
        and ctx_workspace_path is not None
        and Path(ctx_workspace_path).resolve() == workspace_path.resolve()
    ):
        return runtime
    return WorkspacePreferencesRuntime(workspace_path)


def _prefs_payload(runtime: WorkspacePreferencesRuntime) -> dict[str, Any]:
    return runtime.current.model_dump(mode="json")


def _sections_payload() -> list[dict[str, Any]]:
    return [section.model_dump(mode="json") for section in PREFERENCE_SECTIONS]


@preferences_router.get("/preferences")
async def get_preferences(
    request: Request,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    try:
        runtime = _preferences_runtime(request, workspace_id)
        return {
            "ok": True,
            "error": None,
            "data": {
                "preferences": _prefs_payload(runtime),
                "sections": _sections_payload(),
            },
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "data": None}


@preferences_router.patch("/preferences")
async def patch_preferences(
    body: PreferencesPatchRequest,
    request: Request,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    try:
        runtime = _preferences_runtime(request, workspace_id)
        updated = runtime.update_many(body.edits)
        return {
            "ok": True,
            "error": None,
            "data": {
                "changed": sorted(str(path).strip() for path in body.edits),
                "preferences": updated.model_dump(mode="json"),
                "sections": _sections_payload(),
            },
        }
    except PreferencePathError as exc:
        return {"ok": False, "error": str(exc), "data": None}
    except ValidationError as exc:
        return {"ok": False, "error": str(exc), "data": None}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "data": None}
