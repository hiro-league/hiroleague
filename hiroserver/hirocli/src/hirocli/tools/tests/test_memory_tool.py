from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hirocli.domain.data_store import ensure_data_db, get_default_user_id
from hirocli.tools.memory import MemoryClearTool, MemoryListTool
from hirocli.tools.registry import RuntimeContext


class FakeCommManager:
    def __init__(self, workspace_path: Path, memory_service: Any) -> None:
        self.ctx = SimpleNamespace(
            workspace_path=workspace_path,
            memory_service=memory_service,
        )


class FakeMemoryService:
    def __init__(self) -> None:
        self.list_calls: list[dict[str, Any]] = []
        self.clear_calls: list[dict[str, Any]] = []

    async def list_all(
        self,
        *,
        user_id: int,
        character_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self.list_calls.append({"user_id": user_id, "character_id": character_id})
        return [{"memory": "remembered"}]

    async def clear_all(
        self,
        *,
        user_id: int,
        character_id: str | None = None,
    ) -> int:
        self.clear_calls.append({"user_id": user_id, "character_id": character_id})
        return 3


@pytest.mark.asyncio
async def test_runtime_memory_list_uses_attached_service(tmp_path: Path) -> None:
    ensure_data_db(tmp_path)
    user_id = get_default_user_id(tmp_path)
    service = FakeMemoryService()
    tool = MemoryListTool()
    tool.attach_runtime(
        RuntimeContext(FakeCommManager(tmp_path, service), loop=asyncio.get_running_loop())
    )

    result = await tool.execute_async(character_id="hiro")

    assert result.memories == [{"memory": "remembered"}]
    assert service.list_calls == [{"user_id": user_id, "character_id": "hiro"}]


@pytest.mark.asyncio
async def test_runtime_memory_clear_uses_attached_service(tmp_path: Path) -> None:
    ensure_data_db(tmp_path)
    user_id = get_default_user_id(tmp_path)
    service = FakeMemoryService()
    tool = MemoryClearTool()
    tool.attach_runtime(
        RuntimeContext(FakeCommManager(tmp_path, service), loop=asyncio.get_running_loop())
    )

    result = await tool.execute_async(character_id=None)

    assert result.deleted_count == 3
    assert service.clear_calls == [{"user_id": user_id, "character_id": None}]
