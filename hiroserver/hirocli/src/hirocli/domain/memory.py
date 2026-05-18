"""Long-term memory service contract."""

from __future__ import annotations

from typing import Protocol, Any


DEFAULT_USER_ID = "default"


class MemoryService(Protocol):
    async def add(
        self,
        content: str,
        *,
        user_id: str,
        agent_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def search(
        self,
        query: str,
        *,
        user_id: str,
        agent_id: str,
        limit: int = 8,
    ) -> list[dict[str, Any]]: ...

    async def list_all(
        self,
        *,
        user_id: str,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]: ...

    async def clear_all(
        self,
        *,
        user_id: str,
        agent_id: str | None = None,
    ) -> int: ...
