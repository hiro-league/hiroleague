from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hirocli.admin_svelte.routes import memory as memory_route
from hirocli.domain.data_store import ensure_data_db, get_default_user_id


class FakeMemoryService:
    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        *,
        group_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self._rows = rows if rows is not None else [{"memory": "remembered"}]
        self._group_rows = group_rows if group_rows is not None else []
        self.calls: list[dict[str, Any]] = []
        self.deleted_ids: list[str] = []

    async def list_all(
        self,
        *,
        user_id: int,
        character_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append({"user_id": user_id, "character_id": character_id})
        return self._rows

    async def list_facts_in_groups(
        self,
        group_ids: list[str],
    ) -> list[dict[str, Any]]:
        self.calls.append({"group_ids": group_ids})
        return self._group_rows

    async def clear_all(
        self,
        *,
        user_id: int,
        character_id: str | None = None,
    ) -> int:
        self.calls.append({"clear_user_id": user_id, "character_id": character_id})
        count = len(self._rows)
        self._rows = []
        return count

    async def clear_groups(self, group_ids: list[str]) -> int:
        self.calls.append({"clear_group_ids": group_ids})
        return 3

    async def delete(self, memory_id: str) -> None:
        self.deleted_ids.append(memory_id)


@pytest.mark.asyncio
async def test_memory_clear_uses_live_workspace_service(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_data_db(tmp_path)
    user_id = get_default_user_id(tmp_path)
    service = FakeMemoryService([{"id": "1"}, {"id": "2"}])
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                ctx=SimpleNamespace(workspace_path=tmp_path, memory_service=service)
            )
        )
    )
    monkeypatch.setattr(
        memory_route,
        "resolve_workspace",
        lambda workspace_id: (SimpleNamespace(path=str(tmp_path)), None),
    )

    result = await memory_route.clear_workspace_memories("ws-1", request)

    assert result == {"deleted_count": 2}
    assert service.calls == [{"clear_user_id": user_id, "character_id": None}]


@pytest.mark.asyncio
async def test_memory_delete_uses_mem0_memory_id(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeMemoryService()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                ctx=SimpleNamespace(workspace_path=tmp_path, memory_service=service)
            )
        )
    )
    monkeypatch.setattr(
        memory_route,
        "resolve_workspace",
        lambda workspace_id: (SimpleNamespace(path=str(tmp_path)), None),
    )

    result = await memory_route.delete_workspace_memory("mem-1", "ws-1", request)

    assert result == {"memory_id": "mem-1"}
    assert service.deleted_ids == ["mem-1"]


def test_memory_list_uses_live_workspace_service(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The mounted memory library router reads the server's own memory service for its workspace
    (never a second one) and lists the workspace's default user without a group_id."""
    ensure_data_db(tmp_path)
    user_id = get_default_user_id(tmp_path)
    service = FakeMemoryService()

    def fail_create(*_: Any, **__: Any) -> None:
        raise AssertionError("route should not open a second memory service")

    monkeypatch.setattr(memory_route, "create_memory_service", fail_create)
    app = FastAPI()
    app.state.ctx = SimpleNamespace(workspace_path=tmp_path, memory_service=service)
    app.include_router(memory_route.memory_graph_router, prefix="/api")
    app.dependency_overrides[memory_route._selected_workspace] = lambda: tmp_path

    result = TestClient(app).get("/api/memory/list").json()

    assert result == {"memory_enabled": True, "memories": [{"memory": "remembered"}]}
    assert service.calls == [{"user_id": user_id, "character_id": None}]
