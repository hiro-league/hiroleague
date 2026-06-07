"""Admin routes for long-term (Graphiti) memory inspection and deletion."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from hiro_commons.log import Logger

from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import envelope_failure
from hirocli.domain.data_store import get_default_user_id
from hirocli.domain.preferences import load_preferences
from hirocli.domain.workspace import resolve_workspace
from hirocli.services.memory import create_memory_service

log = Logger.get("ADMIN.MEMORY")

memory_router = APIRouter()


def _live_memory_service(request: Request, workspace_path: Path) -> tuple[bool, Any | None]:
    state = getattr(getattr(request, "app", None), "state", None)
    ctx = getattr(state, "ctx", None)
    ctx_workspace_path = getattr(ctx, "workspace_path", None)
    if ctx_workspace_path is None:
        return False, None
    try:
        is_live_workspace = Path(ctx_workspace_path).resolve() == workspace_path.resolve()
    except OSError:
        is_live_workspace = Path(ctx_workspace_path) == workspace_path
    if not is_live_workspace:
        return False, None
    return True, getattr(ctx, "memory_service", None)


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("metadata")
    return value if isinstance(value, dict) else {}


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    meta = _metadata(row)
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
        if key in meta and meta[key] not in (None, ""):
            return meta[key]
    return None


def _timestamp_seconds(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric / 1000 if numeric > 10_000_000_000 else numeric
    if isinstance(value, str):
        text = value.strip()
        try:
            numeric = float(text)
            return numeric / 1000 if numeric > 10_000_000_000 else numeric
        except ValueError:
            pass
        try:
            parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed.timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _memory_updated_sort_key(row: dict[str, Any]) -> float:
    updated = _first_value(row, "updated_at", "updatedAt", "updated")
    created = _first_value(row, "created_at", "createdAt", "created")
    return _timestamp_seconds(updated) or _timestamp_seconds(created)


def _sort_memories(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(memories, key=_memory_updated_sort_key, reverse=True)


def _success(data: Any) -> dict[str, Any]:
    return {"ok": True, "error": None, "data": data}


def _service_unavailable() -> dict[str, Any]:
    return envelope_failure("Memory service is disabled or unavailable.")


async def _resolve_memory_service(
    request: Request,
    workspace_id: str | None,
) -> tuple[Any | None, Path]:
    entry, _ = resolve_workspace(workspace_id)
    workspace_path = Path(entry.path)
    is_live_workspace, service = _live_memory_service(request, workspace_path)
    if not is_live_workspace:
        prefs = load_preferences(workspace_path)
        service = create_memory_service(workspace_path, prefs)
    return service, workspace_path


@memory_router.get("/memory/list")
async def list_workspace_memories(
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
    group_id: str | None = None,
) -> dict[str, Any]:
    """List memories. Default (no ``group_id``): all of the workspace default user's
    conversation-memory groups. With ``group_id``: that one partition's facts — lets the
    Memories group selector show ANY group (memory / knowledge / eval), mirroring the Graph
    tab. The client-supplied scope is re-validated at this API boundary (firm group policy,
    docs/graph-group-policy-design.md §6) so a crafted/empty id can't trigger an all-groups
    scan."""
    try:
        service, workspace_path = await _resolve_memory_service(request, workspace_id)
        if service is None:
            return _success({"memory_enabled": False, "memories": []})
        gid = (group_id or "").strip()
        if gid:
            # Group filter: re-mint the untrusted client scope against the closed grammar.
            from hirocli.services.knowledge.graph.group_scope import (
                GroupPolicyError,
                validate_group_id,
            )

            try:
                gid = validate_group_id(gid)
            except GroupPolicyError as exc:
                return envelope_failure(f"Invalid memory group: {exc}")
            memories = _sort_memories(await service.list_facts_in_groups([gid]))
        else:
            memories = _sort_memories(
                await service.list_all(user_id=get_default_user_id(workspace_path))
            )
        return _success({"memory_enabled": True, "memories": memories})
    except Exception as exc:
        log.error("list memories - admin failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@memory_router.post("/memory/clear")
async def clear_workspace_memories(
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    """Delete all long-term memories for the workspace default user."""
    try:
        service, workspace_path = await _resolve_memory_service(request, workspace_id)
        if service is None:
            return _service_unavailable()
        deleted = await service.clear_all(user_id=get_default_user_id(workspace_path))
        return _success({"deleted_count": deleted})
    except Exception as exc:
        log.error("clear memories - admin failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@memory_router.post("/memory/delete")
async def delete_workspace_memories(
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    """Delete several long-term memories (Graphiti fact edges) by id — backs the admin
    "Clear shown" action over the displayed/filtered rows. Idempotent for missing ids."""
    try:
        body = await request.json()
        ids = body.get("ids") if isinstance(body, dict) else None
        if not isinstance(ids, list):
            return envelope_failure("'ids' must be a list of memory ids.")
        service, _ = await _resolve_memory_service(request, workspace_id)
        if service is None:
            return _service_unavailable()
        deleted = await service.delete_many([str(i) for i in ids if str(i).strip()])
        return _success({"deleted_count": deleted})
    except Exception as exc:
        log.error("delete memories (batch) - admin failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@memory_router.delete("/memory/{memory_id}")
async def delete_workspace_memory(
    memory_id: str,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    """Delete one long-term memory (Graphiti fact edge) by id."""
    try:
        service, _ = await _resolve_memory_service(request, workspace_id)
        if service is None:
            return _service_unavailable()
        mid = str(memory_id or "").strip()
        if not mid:
            return envelope_failure("Memory id is required.")
        await service.delete(mid)
        return _success({"memory_id": mid})
    except Exception as exc:
        log.error("delete memory - admin failed", memory_id=memory_id, error=str(exc), exc_info=True)
        return envelope_failure(str(exc))
