"""Long-term memory service contract."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from hirocli.services.memory.usage_capture import MemoryAddResult


def mem0_history_db_path(workspace_path: Path) -> Path:
    """Path to mem0's SQLite history DB (workspace-local).

    Mem0 keeps two tables in this file:
    - ``messages``: rolling last-10 raw turns per session, fed back into the
      extraction LLM as ``last_k_messages`` on every ``Memory.add`` call.
    - ``history``: per-memory ADD/UPDATE/DELETE change log (audit only).

    Pointing this into the workspace (instead of mem0's default ``~/.mem0``)
    is what lets ``clear_channel_messages`` wipe the buffer deterministically
    without leaking state across workspaces.
    """
    return Path(workspace_path) / "memory" / "history.db"


def mem0_session_scope(
    *,
    user_id: str,
    run_id: str | None = None,
) -> str:
    """Replicate mem0's ``session_scope`` key for rows Hiro writes.

    Mirrors ``mem0/memory/main.py::_build_session_scope`` (sorted keys joined
    by ``&``). Conversation isolation uses ``run_id=<channel_id>`` because
    mem0's ``run_id`` is also persisted on long-term records and should point
    to the actual thread/conversation, not a character slug.
    """
    parts: list[str] = []
    for key, val in sorted([("user_id", user_id), ("run_id", run_id)]):
        if val:
            parts.append(f"{key}={val}")
    return "&".join(parts)


def resolve_memory_user_id(*, data_user_id: int | None, workspace_path: Path) -> int:
    """Return ``data.db`` user id from graph state, else the workspace default."""
    from .data_store import get_default_user_id

    if data_user_id is not None:
        return int(data_user_id)
    return get_default_user_id(workspace_path)


class MemoryService(Protocol):
    async def add(
        self,
        content: str,
        *,
        user_id: int,
        run_id: str,
        character_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> "MemoryAddResult":
        """Store a turn; return LLM usage and the count of memories actually stored."""
        ...

    async def search(
        self,
        query: str,
        *,
        user_id: int,
        character_id: str,
        limit: int = 8,
    ) -> list[dict[str, Any]]: ...

    async def list_all(
        self,
        *,
        user_id: int,
        character_id: str | None = None,
    ) -> list[dict[str, Any]]: ...

    async def clear_all(
        self,
        *,
        user_id: int,
        character_id: str | None = None,
    ) -> int: ...

    async def delete(
        self,
        memory_id: str,
    ) -> None: ...
