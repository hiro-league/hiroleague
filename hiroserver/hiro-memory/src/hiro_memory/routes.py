"""The HTTP routes behind the UI kit's graph viewer and memories table.

``graph_routes(...)`` builds one router; its owner mounts it under ``/api`` (the core's admin does; EvalHiro
will). The routes read the graph and the conversation memory of one workspace folder, which the owner's
``workspace`` dependency names for each request, and keep the URLs the core's admin always had:

- ``POST /knowledge/graph/export``, ``GET /knowledge/graph/groups``, ``POST /knowledge/graph/episodes``
- ``POST /knowledge/graph/chunks-detail``, ``POST /knowledge/graph/search-chunks``
- ``GET /memory/list``, ``POST /memory/delete``, ``POST /memory/clear-group``

Every client-supplied group id is re-validated against the closed group grammar before any read or write
(docs/graph-group-policy-design.md §6). A failure answers ``{"detail": ...}`` with status 400, as FastAPI's
own errors do.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from hiro_commons.log import Logger
from pydantic import BaseModel

from .graph.graphiti_service import is_kuzu_lock_error
from .graph.group_scope import KNOWLEDGE_GROUP_ID, GroupPolicyError, validate_group_id
from .graph.views import (
    graph_episodes_payload,
    graph_groups_payload,
    graph_snapshot_payload,
    kuzu_chunk_details,
)

log = Logger.get("MEMORY.ROUTES")

_BUSY = "Graph database is busy (a build may be running in another process) — try again shortly."


class MemoryStore(Protocol):
    """What the memory routes call on the owner's conversation memory."""

    async def list_all(self, *, user_id: int) -> list[dict[str, Any]]: ...
    async def list_facts_in_groups(self, group_ids: list[str]) -> list[dict[str, Any]]: ...
    async def delete_many(self, memory_ids: list[str]) -> int: ...
    async def clear_groups(self, group_ids: list[str]) -> int: ...


# The owner's hooks. ``memory`` answers None when memory is off for that workspace.
MemoryFor = Callable[[Request, Path], Awaitable[MemoryStore | None]]
ChunkDetails = Callable[[Request, Path, list[str]], Awaitable[list[dict[str, Any]]]]
ChunkSearch = Callable[[Request, Path, str, int], Awaitable[list[str]]]


class GraphExportBody(BaseModel):
    """Graph export request. ``node_types`` / ``document_id`` are reserved for later filters and ignored;
    the limits are safety caps. ``group_ids`` selects the partitions (default: the knowledge group)."""

    node_types: list[str] | None = None
    document_id: str | None = None
    node_limit: int | None = None
    edge_limit: int | None = None
    group_ids: list[str] | None = None


class GraphEpisodesBody(BaseModel):
    """A partition's episodes, for the Graph tab's episode multi-select."""

    group_id: str | None = None
    limit: int = 2000


class GraphChunksDetailBody(BaseModel):
    """Resolve a selected node/edge's provenance chunk_ids to text."""

    chunk_ids: list[str] = []


class GraphSearchChunksBody(BaseModel):
    """Chunk-text search: find chunk ids whose text matches ``text``."""

    text: str = ""
    limit: int = 200


class MemoryDeleteBody(BaseModel):
    ids: list[str] | None = None


class MemoryClearGroupBody(BaseModel):
    group_id: str | None = None


def _failure(error: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"detail": error}, status_code=status_code)


def _graph_failure(what: str, exc: Exception) -> JSONResponse:
    # With the shared driver, in-process opens no longer collide; a lock error means an EXTERNAL process
    # holds the file (a 2nd server / stale handle). Answer "busy" instead of a raw stack.
    if is_kuzu_lock_error(exc):
        log.warning("⚠️ graph %s — graph DB busy (external lock held)", what)
        return _failure(_BUSY)
    log.error(f"graph {what} failed", error=str(exc), exc_info=True)
    return _failure(str(exc))


# --- memory ordering -------------------------------------------------------------------------------


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
        except (ValueError, OverflowError, OSError):
            # datetime.timestamp() raises OSError [Errno 22] on Windows (and OverflowError elsewhere)
            # for out-of-range dates — pre-1970, year-0001, or far-future — which a Graphiti fact can
            # carry as a weird extracted valid_at/created_at (e.g. a BEAM eval fact). Sort those as
            # epoch-0 instead of failing the entire Memories list for that group.
            return 0.0
    return 0.0


def _memory_updated_sort_key(row: dict[str, Any]) -> float:
    updated = _first_value(row, "updated_at", "updatedAt", "updated")
    created = _first_value(row, "created_at", "createdAt", "created")
    return _timestamp_seconds(updated) or _timestamp_seconds(created)


def sort_memories(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Newest first, by when each memory was last updated (else created)."""
    return sorted(memories, key=_memory_updated_sort_key, reverse=True)


# --- the router ------------------------------------------------------------------------------------


def graph_routes(
    *,
    workspace: Callable[..., Path],
    memory: MemoryFor,
    query_timeout: Callable[[Path], int] = lambda _path: 60,
    default_user_id: Callable[[Path], int] | None = None,
    chunk_details: ChunkDetails | None = None,
    search_chunks: ChunkSearch | None = None,
) -> APIRouter:
    """The graph viewer's and memories table's routes over one workspace folder per request.

    - ``workspace``: a FastAPI dependency answering the folder that holds ``db/graphiti_kuzu.db``.
    - ``memory``: the conversation memory for that folder (None when it is off).
    - ``query_timeout``: the graph reads' per-query timeout, in seconds.
    - ``default_user_id``: whose memory ``/memory/list`` shows without a ``group_id``; without it a
      ``group_id`` is required.
    - ``chunk_details`` / ``search_chunks``: a node's chunk text and the chunk-text search. By default the
      text comes from Kuzu (memory groups) and the search finds nothing; an owner with a knowledge base
      hands in its own lookups, which cover both.
    """
    router = APIRouter()
    workspace_dep = Depends(workspace)

    @router.post("/knowledge/graph/export")
    async def graph_export(body: GraphExportBody, path: Path = workspace_dep) -> Any:
        """Whole-graph export, the Graph tab's load path. Empty graph when none is built yet."""
        try:
            # The viewer is for people allowed to see every partition; validation rejects only
            # malformed, empty or unknown-namespace ids (never an all-groups scan).
            try:
                groups = [validate_group_id(g) for g in body.group_ids] if body.group_ids else None
            except GroupPolicyError as exc:
                return _failure(f"Invalid graph group: {exc}")
            return await graph_snapshot_payload(
                path,
                node_limit=body.node_limit,
                edge_limit=body.edge_limit,
                group_ids=groups,
                query_timeout_s=query_timeout(path),
            )
        except Exception as exc:
            return _graph_failure("export", exc)

    @router.get("/knowledge/graph/groups")
    async def graph_groups(path: Path = workspace_dep) -> Any:
        """The graph's partitions for the group selector. Empty when no graph is built yet."""
        try:
            return await graph_groups_payload(path, query_timeout_s=query_timeout(path))
        except Exception as exc:
            return _graph_failure("groups", exc)

    @router.post("/knowledge/graph/episodes")
    async def graph_episodes(body: GraphEpisodesBody, path: Path = workspace_dep) -> Any:
        """A partition's episodes (id + snippet + valid_at), in corpus order. Defaults to the
        knowledge group."""
        try:
            try:
                group_id = validate_group_id((body.group_id or "").strip() or KNOWLEDGE_GROUP_ID)
            except GroupPolicyError as exc:
                return _failure(f"Invalid graph group: {exc}")
            limit = max(1, min(int(body.limit or 2000), 5000))
            return await graph_episodes_payload(
                path, group_id, limit=limit, query_timeout_s=query_timeout(path)
            )
        except Exception as exc:
            return _graph_failure("episodes", exc)

    @router.post("/knowledge/graph/chunks-detail")
    async def graph_chunks_detail(
        body: GraphChunksDetailBody, request: Request, path: Path = workspace_dep
    ) -> Any:
        """Chunk text + source titles for a selected node/edge's chunk_ids."""
        # Cap one selection's lookup — a node rolls up the chunks of every touching edge.
        ids = [str(c) for c in (body.chunk_ids or []) if c][:200]
        if not ids:
            return {"chunks": []}
        try:
            if chunk_details is not None:
                return {"chunks": await chunk_details(request, path, ids)}
            return {
                "chunks": await kuzu_chunk_details(path, ids, query_timeout_s=query_timeout(path))
            }
        except Exception as exc:
            return _graph_failure("chunks-detail", exc)

    @router.post("/knowledge/graph/search-chunks")
    async def graph_search_chunks(
        body: GraphSearchChunksBody, request: Request, path: Path = workspace_dep
    ) -> Any:
        """Chunk-text search → matching chunk ids, which the Graph tab maps onto nodes/edges.
        Blank query → empty result."""
        text = (body.text or "").strip()
        if not text or search_chunks is None:
            return {"point_ids": []}
        # Cap the scan so a hot search box can't sweep an unbounded collection per keystroke.
        limit = max(1, min(int(body.limit or 200), 500))
        try:
            return {"point_ids": await search_chunks(request, path, text, limit)}
        except Exception as exc:
            return _graph_failure("search-chunks", exc)

    @router.get("/memory/list")
    async def list_memories(
        request: Request, group_id: str | None = None, path: Path = workspace_dep
    ) -> Any:
        """With ``group_id``: that partition's facts (any memory, knowledge or eval group). Without it:
        the default user's conversation-memory groups."""
        try:
            service = await memory(request, path)
            if service is None:
                return {"memory_enabled": False, "memories": []}
            gid = (group_id or "").strip()
            if gid:
                try:
                    gid = validate_group_id(gid)
                except GroupPolicyError as exc:
                    return _failure(f"Invalid memory group: {exc}")
                rows = await service.list_facts_in_groups([gid])
            elif default_user_id is not None:
                rows = await service.list_all(user_id=default_user_id(path))
            else:
                return _failure("'group_id' is required.")
            return {"memory_enabled": True, "memories": sort_memories(rows)}
        except Exception as exc:
            log.error("list memories failed", error=str(exc), exc_info=True)
            return _failure(str(exc))

    @router.post("/memory/delete")
    async def delete_memories(
        body: MemoryDeleteBody, request: Request, path: Path = workspace_dep
    ) -> Any:
        """Delete several memories (fact edges) by id — the table's "Clear shown". Idempotent for
        missing ids."""
        if not isinstance(body.ids, list):
            return _failure("'ids' must be a list of memory ids.")
        try:
            service = await memory(request, path)
            if service is None:
                return _failure("Memory service is disabled or unavailable.")
            deleted = await service.delete_many([str(i) for i in body.ids if str(i).strip()])
            return {"deleted_count": deleted}
        except Exception as exc:
            log.error("delete memories failed", error=str(exc), exc_info=True)
            return _failure(str(exc))

    @router.post("/memory/clear-group")
    async def clear_group(
        body: MemoryClearGroupBody, request: Request, path: Path = workspace_dep
    ) -> Any:
        """Wipe ONE partition: facts, entities, episodes and communities. Answers the episode count
        removed."""
        gid = (body.group_id or "").strip()
        if not gid:
            return _failure("'group_id' is required.")
        try:
            gid = validate_group_id(gid)
        except GroupPolicyError as exc:
            return _failure(f"Invalid memory group: {exc}")
        try:
            service = await memory(request, path)
            if service is None:
                return _failure("Memory service is disabled or unavailable.")
            return {"deleted_count": await service.clear_groups([gid])}
        except Exception as exc:
            log.error("clear group failed", error=str(exc), exc_info=True)
            return _failure(str(exc))

    return router
