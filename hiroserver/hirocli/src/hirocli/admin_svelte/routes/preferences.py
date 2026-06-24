"""Workspace preferences routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import ValidationError

from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.schemas import PreferencesPatchRequest
from hirocli.domain.preferences import (
    PREFERENCE_SECTIONS,
    PROMPT_DEFAULTS,
    knowledge_answering_model_source,
    resolve_knowledge_answering_llm,
)
from hirocli.domain.preferences_schema import workspace_preferences_schema_payload
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


def _prefs_payload(
    runtime: WorkspacePreferencesRuntime,
    *,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    prefs = runtime.current
    payload = prefs.model_dump(mode="json")
    knowledge = payload.setdefault("knowledge", {})
    answering = knowledge.setdefault("answering", {})
    knowledge["default_embedding_model_resolved"] = prefs.knowledge.default_embedding_model_resolved
    resolved = resolve_knowledge_answering_llm(
        prefs,
        runtime._workspace_path,
        workspace_id=workspace_id,
    )
    answering["model_resolved"] = resolved.model_id if resolved is not None else None
    answering["model_resolved_source"] = knowledge_answering_model_source(prefs)
    from hirocli.services.knowledge import count_knowledge_points

    knowledge["default_embedding_model_locked"] = count_knowledge_points(runtime._workspace_path) > 0
    return payload


def _sections_payload() -> list[dict[str, Any]]:
    return [section.model_dump(mode="json") for section in PREFERENCE_SECTIONS]


@preferences_router.get("/preferences/schema")
async def get_preferences_schema() -> dict[str, Any]:
    """Static field metadata for the admin preferences UI (bounds, defaults, hints)."""
    try:
        return {
            "ok": True,
            "error": None,
            "data": workspace_preferences_schema_payload(),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "data": None}


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
                "preferences": _prefs_payload(runtime, workspace_id=workspace_id),
                "sections": _sections_payload(),
                # Built-in default texts for the editable system prompts, so the UI can offer
                # "Restore default" (a cleared prompt persists "" and the pydantic default never
                # re-applies — the default text is otherwise unrecoverable from the admin UI).
                "prompt_defaults": dict(PROMPT_DEFAULTS),
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
                "preferences": _prefs_payload(runtime, workspace_id=workspace_id),
                "sections": _sections_payload(),
                # Same map as GET — the controller refreshes its state from the PATCH response.
                "prompt_defaults": dict(PROMPT_DEFAULTS),
            },
        }
    except PreferencePathError as exc:
        return {"ok": False, "error": str(exc), "data": None}
    except ValidationError as exc:
        return {"ok": False, "error": str(exc), "data": None}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "data": None}
