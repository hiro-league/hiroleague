"""Long-term memory service contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class MemoryUsage:
    """Aggregated LLM usage for one memory write operation."""

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    reasoning_tokens: int
    call_count: int


@dataclass(frozen=True)
class MemoryAddResult:
    """Outcome of a single :meth:`MemoryService.add` call.

    ``stored_count`` is how many memories the backend actually stored this turn
    (mem0: vector rows written; Graphiti: facts learned). ``usage`` may be ``None``
    when token accounting is owned elsewhere (e.g. the Graph-Runs ledger for the
    Graphiti backend). These types are the *contract's* result types, so they live in
    the domain layer — every backend (mem0, Graphiti) returns them."""

    usage: MemoryUsage | None
    stored_count: int
    stored_items: tuple[dict[str, Any], ...] = ()


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
        ledger_sink: Any | None = None,
    ) -> "MemoryAddResult":
        """Store a turn; return the count of memories actually stored.

        ``ledger_sink`` (the chat turn's Graph-Runs sink) makes the backend's write steps
        observable in Graph Runs; ``None`` = no ledger (CLI/tools/tests)."""
        ...

    async def search(
        self,
        query: str,
        *,
        user_id: int,
        character_id: str,
        limit: int | None = None,
        threshold: float | None = None,
        rerank: bool | None = None,
        metadata_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    async def list_all(
        self,
        *,
        user_id: int,
        character_id: str | None = None,
    ) -> list[dict[str, Any]]: ...

    async def list_facts_in_groups(
        self,
        group_ids: list[str],
    ) -> list[dict[str, Any]]:
        """List facts for explicit graph partitions (any namespace) — backs the admin
        Memories group selector, which can point at memory / knowledge / eval groups."""
        ...

    async def clear_all(
        self,
        *,
        user_id: int,
        character_id: str | None = None,
    ) -> int: ...

    async def clear_groups(
        self,
        group_ids: list[str],
    ) -> int:
        """Wipe whole graph partitions (facts + entities + episodes + communities) — backs
        the admin "Clear group" action over the selected partition."""
        ...

    async def delete(
        self,
        memory_id: str,
    ) -> None: ...
