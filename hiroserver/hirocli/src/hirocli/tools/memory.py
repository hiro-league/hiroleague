"""Long-term memory inspection tools."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.data_store import get_default_user_id
from ..domain.preferences import load_preferences
from ..domain.workspace import resolve_workspace
from ..services.memory import create_memory_service
from .base import Tool, ToolParam


def _resolve_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


def _runtime_workspace(runtime: Any | None) -> Path | None:
    if runtime is None:
        return None
    comm = getattr(runtime, "comm_manager", None)
    ctx = getattr(comm, "ctx", None)
    workspace_path = getattr(ctx, "workspace_path", None)
    return Path(workspace_path) if workspace_path is not None else None


def _runtime_service(runtime: Any | None):
    if runtime is None:
        return None
    comm = getattr(runtime, "comm_manager", None)
    ctx = getattr(comm, "ctx", None)
    return getattr(ctx, "memory_service", None)


def _service(workspace_path: Path):
    prefs = load_preferences(workspace_path)
    service = create_memory_service(workspace_path, prefs)
    if service is None:
        raise RuntimeError("Memory service is disabled or unavailable.")
    return service


def _memory_user_id(workspace_path: Path) -> int:
    return get_default_user_id(workspace_path)


def _resolve_list_clear_context(
    runtime: Any | None,
    workspace: str | None,
) -> tuple[Any, int]:
    rt_path = _runtime_workspace(runtime)
    service = _runtime_service(runtime)
    if service is None:
        if rt_path is not None:
            raise RuntimeError("Memory service is disabled or unavailable.")
        rt_path = _resolve_path(workspace)
        service = _service(rt_path)
    elif rt_path is None:
        rt_path = _resolve_path(workspace)
    return service, _memory_user_id(rt_path)


@dataclass
class MemoryListResult:
    memories: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MemoryClearResult:
    deleted_count: int


class MemoryListTool(Tool):
    runtime = True
    name = "memory_list"
    description = "List long-term memories for the current user, optionally scoped to a character"
    params = {
        "character_id": ToolParam(str, "Character id to filter by", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(
        self,
        character_id: str | None = None,
        workspace: str | None = None,
        *,
        workspace_path: Path | None = None,
    ) -> MemoryListResult:
        resolved = workspace_path or _resolve_path(workspace)
        memories = asyncio.run(
            _service(resolved).list_all(
                user_id=_memory_user_id(resolved),
                character_id=(character_id or None),
            )
        )
        return MemoryListResult(memories=memories)

    async def execute_async(
        self,
        character_id: str | None = None,
        workspace: str | None = None,
    ) -> MemoryListResult:
        service, user_id = _resolve_list_clear_context(
            getattr(self, "_runtime", None),
            workspace,
        )
        memories = await service.list_all(
            user_id=user_id,
            character_id=(character_id or None),
        )
        return MemoryListResult(memories=memories)


class MemoryClearTool(Tool):
    runtime = True
    agent_default = False
    name = "memory_clear"
    description = "Delete long-term memories for the current user, optionally scoped to a character"
    params = {
        "character_id": ToolParam(str, "Character id to filter by", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(
        self,
        character_id: str | None = None,
        workspace: str | None = None,
        *,
        workspace_path: Path | None = None,
    ) -> MemoryClearResult:
        resolved = workspace_path or _resolve_path(workspace)
        deleted = asyncio.run(
            _service(resolved).clear_all(
                user_id=_memory_user_id(resolved),
                character_id=(character_id or None),
            )
        )
        return MemoryClearResult(deleted_count=deleted)

    async def execute_async(
        self,
        character_id: str | None = None,
        workspace: str | None = None,
    ) -> MemoryClearResult:
        service, user_id = _resolve_list_clear_context(
            getattr(self, "_runtime", None),
            workspace,
        )
        deleted = await service.clear_all(
            user_id=user_id,
            character_id=(character_id or None),
        )
        return MemoryClearResult(deleted_count=deleted)
