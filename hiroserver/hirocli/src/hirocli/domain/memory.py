"""Long-term memory service contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from hiro_memory.conversation.results import MemoryAddResult


def resolve_memory_user_id(*, data_user_id: int | None, workspace_path: Path) -> int:
    """Return ``data.db`` user id from graph state, else the workspace default."""
    from .data_store import get_default_user_id

    if data_user_id is not None:
        return int(data_user_id)
    return get_default_user_id(workspace_path)


def speaker_name(workspace_path: Path, user_id: int | None, preferred: str) -> str:
    """The name memory anchors a chat user's facts to (Permissions phase 3). The owner's chat user (the seeded one)
    keeps the ``memory.user_name`` preference, which their memory so far is anchored to; anyone else is what Hiro
    calls them in the family list, never the owner's name."""
    from .data_store import get_default_user_id, person_of_chat_user
    from .people import get_person

    uid = resolve_memory_user_id(data_user_id=user_id, workspace_path=workspace_path)
    if uid == get_default_user_id(workspace_path):
        return preferred
    person_id = person_of_chat_user(workspace_path, uid)
    person = get_person(workspace_path, person_id) if person_id else None
    return person.hiro_calls_them if person else ""


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
