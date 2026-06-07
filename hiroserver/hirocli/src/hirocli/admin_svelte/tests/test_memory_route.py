from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

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

    async def delete(self, memory_id: str) -> None:
        self.deleted_ids.append(memory_id)


@pytest.mark.asyncio
async def test_memory_list_uses_live_workspace_service(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_data_db(tmp_path)
    user_id = get_default_user_id(tmp_path)
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

    def fail_create(*_: Any, **__: Any) -> None:
        raise AssertionError("route should not open a second memory service")

    monkeypatch.setattr(memory_route, "create_memory_service", fail_create)

    result = await memory_route.list_workspace_memories("ws-1", request)

    assert result["ok"] is True
    assert result["data"] == {
        "memory_enabled": True,
        "memories": [{"memory": "remembered"}],
    }
    assert service.calls == [{"user_id": user_id, "character_id": None}]


@pytest.mark.asyncio
async def test_memory_list_orders_by_updated_desc(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeMemoryService(
        [
            {"id": "old", "memory": "old", "updated_at": "2026-05-17T12:00:00Z"},
            {"id": "new", "memory": "new", "updated_at": "2026-05-18T12:00:00Z"},
            {"id": "created-only", "memory": "created", "created_at": "2026-05-18T10:00:00Z"},
        ]
    )
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

    result = await memory_route.list_workspace_memories("ws-1", request)

    assert [row["id"] for row in result["data"]["memories"]] == ["new", "created-only", "old"]


@pytest.mark.asyncio
async def test_memory_list_group_filter_reads_that_partition(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With ?group_id=, the route reads that one partition via list_facts_in_groups (the group
    # selector path) instead of the default user's list_all — lets the Memories list show any
    # group (memory / knowledge / eval), like the Graph tab.
    service = FakeMemoryService(group_rows=[{"id": "k1", "memory": "kb fact", "source": "knowledge"}])
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

    result = await memory_route.list_workspace_memories("ws-1", request, group_id="kb_main")

    assert result["ok"] is True
    assert result["data"]["memories"] == [{"id": "k1", "memory": "kb fact", "source": "knowledge"}]
    assert service.calls == [{"group_ids": ["kb_main"]}]


@pytest.mark.asyncio
async def test_memory_list_group_filter_rejects_unknown_namespace(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The client scope is re-validated at the API boundary: an out-of-grammar group is rejected,
    # never read (no all-groups fallthrough).
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

    result = await memory_route.list_workspace_memories("ws-1", request, group_id="bogus_group")

    assert result["ok"] is False
    assert service.calls == []


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

    assert result["ok"] is True
    assert result["data"] == {"deleted_count": 2}
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

    assert result["ok"] is True
    assert result["data"] == {"memory_id": "mem-1"}
    assert service.deleted_ids == ["mem-1"]
