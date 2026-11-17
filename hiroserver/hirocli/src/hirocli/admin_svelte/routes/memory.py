"""Admin routes for long-term (Graphiti) memory and the graph viewer.

The routes the UI kit's graph viewer and memories table call are the memory library's
(``hiro_memory.routes.graph_routes``), mounted here with the core's hooks: the selected workspace, its
live (or a new) memory service, ``graph.query_timeout_s``, the workspace's default user, and the
knowledge base's chunk text and search. The two routes no kit piece calls stay here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from hiro_commons.log import Logger
from hiro_memory.routes import graph_routes

from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import api_failure
from hirocli.domain.data_store import get_default_user_id
from hirocli.domain.preferences import load_preferences
from hirocli.domain.workspace import resolve_workspace
from hirocli.services.knowledge.graph_factory import graph_query_timeout
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


async def _memory_for(request: Request, workspace_path: Path) -> Any | None:
    """The server's own memory service for its workspace, else one built from that workspace's
    preferences (None when memory is off there)."""
    is_live_workspace, service = _live_memory_service(request, workspace_path)
    if not is_live_workspace:
        service = create_memory_service(workspace_path, load_preferences(workspace_path))
    return service


def _selected_workspace(workspace_id: SelectedWorkspaceIdDep) -> Path:
    entry, _ = resolve_workspace(workspace_id)
    return Path(entry.path).resolve()


async def _chunk_details(request: Request, workspace_path: Path, ids: list[str]) -> list[dict[str, Any]]:
    # The knowledge service covers both kinds of chunk: Qdrant for knowledge, Kuzu for memory.
    from hirocli.admin_svelte.routes.knowledge import _close_if_owned, knowledge_service_for

    service, owned = knowledge_service_for(request, workspace_path)
    try:
        return await service.get_chunk_details(ids)
    finally:
        await _close_if_owned(service, owned)


async def _search_chunks(request: Request, workspace_path: Path, text: str, limit: int) -> list[str]:
    from hirocli.admin_svelte.routes.knowledge import _close_if_owned, knowledge_service_for

    service, owned = knowledge_service_for(request, workspace_path)
    try:
        return await service.search_chunk_ids_by_text(text, limit=limit)
    finally:
        await _close_if_owned(service, owned)


memory_graph_router = graph_routes(
    workspace=_selected_workspace,
    memory=_memory_for,
    query_timeout=graph_query_timeout,
    default_user_id=get_default_user_id,
    chunk_details=_chunk_details,
    search_chunks=_search_chunks,
)


def _service_unavailable() -> Any:
    return api_failure("Memory service is disabled or unavailable.")


@memory_router.post("/memory/clear")
async def clear_workspace_memories(
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> Any:
    """Delete all long-term memories for the workspace default user."""
    try:
        workspace_path = _selected_workspace(workspace_id)
        service = await _memory_for(request, workspace_path)
        if service is None:
            return _service_unavailable()
        deleted = await service.clear_all(user_id=get_default_user_id(workspace_path))
        return {"deleted_count": deleted}
    except Exception as exc:
        log.error("clear memories - admin failed", error=str(exc), exc_info=True)
        return api_failure(str(exc))


@memory_router.delete("/memory/{memory_id}")
async def delete_workspace_memory(
    memory_id: str,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> Any:
    """Delete one long-term memory (Graphiti fact edge) by id."""
    try:
        service = await _memory_for(request, _selected_workspace(workspace_id))
        if service is None:
            return _service_unavailable()
        mid = str(memory_id or "").strip()
        if not mid:
            return api_failure("Memory id is required.")
        await service.delete(mid)
        return {"memory_id": mid}
    except Exception as exc:
        log.error("delete memory - admin failed", memory_id=memory_id, error=str(exc), exc_info=True)
        return api_failure(str(exc))
