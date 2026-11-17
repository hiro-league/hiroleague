"""The graph viewer's and memories table's router, over a temp workspace and a fake memory store."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hiro_memory.routes import graph_routes, sort_memories


class _FakeMemory:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def list_all(self, *, user_id: int) -> list[dict[str, Any]]:
        self.calls.append(("list_all", user_id))
        return [{"id": "a", "created_at": "2026-01-01T00:00:00Z"}, {"id": "b", "created_at": "2026-03-01T00:00:00Z"}]

    async def list_facts_in_groups(self, group_ids: list[str]) -> list[dict[str, Any]]:
        self.calls.append(("list_facts_in_groups", group_ids))
        return [{"id": "f1"}]

    async def delete_many(self, memory_ids: list[str]) -> int:
        self.calls.append(("delete_many", memory_ids))
        return len(memory_ids)

    async def clear_groups(self, group_ids: list[str]) -> int:
        self.calls.append(("clear_groups", group_ids))
        return 3


def _client(tmp_path: Path, memory: _FakeMemory | None, **hooks: Any) -> TestClient:
    async def memory_for(_request: Any, _path: Path) -> _FakeMemory | None:
        return memory

    app = FastAPI()
    app.include_router(graph_routes(workspace=lambda: tmp_path, memory=memory_for, **hooks), prefix="/api")
    return TestClient(app)


def test_graph_reads_are_empty_without_a_graph(tmp_path: Path) -> None:
    client = _client(tmp_path, _FakeMemory())
    assert client.get("/api/knowledge/graph/groups").json() == {"default_group_id": None, "groups": []}
    export = client.post("/api/knowledge/graph/export", json={}).json()
    assert export["nodes"] == [] and export["edges"] == [] and export["truncated"] is False
    assert client.post("/api/knowledge/graph/episodes", json={"group_id": "mem_1_hiro"}).json() == {
        "episodes": []
    }
    # Reads never create the graph file.
    assert not (tmp_path / "db" / "graphiti_kuzu.db").exists()


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("post", "/api/knowledge/graph/export", {"group_ids": ["../etc"]}),
        ("post", "/api/knowledge/graph/episodes", {"group_id": "nope"}),
        ("post", "/api/memory/clear-group", {"group_id": "nope"}),
    ],
)
def test_untrusted_group_ids_are_refused(tmp_path: Path, method: str, url: str, body: dict) -> None:
    memory = _FakeMemory()
    response = getattr(_client(tmp_path, memory), method)(url, json=body)
    assert response.status_code == 400
    assert "group" in response.json()["detail"].lower()
    assert memory.calls == []


def test_memory_list_by_group_and_by_default_user(tmp_path: Path) -> None:
    memory = _FakeMemory()
    client = _client(tmp_path, memory, default_user_id=lambda _path: 7)
    assert client.get("/api/memory/list", params={"group_id": "mem_7_hiro"}).json() == {
        "memory_enabled": True,
        "memories": [{"id": "f1"}],
    }
    listed = client.get("/api/memory/list").json()
    assert [m["id"] for m in listed["memories"]] == ["b", "a"]  # newest first
    assert memory.calls == [("list_facts_in_groups", ["mem_7_hiro"]), ("list_all", 7)]


def test_memory_list_needs_a_group_without_a_default_user(tmp_path: Path) -> None:
    response = _client(tmp_path, _FakeMemory()).get("/api/memory/list")
    assert response.status_code == 400 and "group_id" in response.json()["detail"]


def test_memory_off_answers_disabled(tmp_path: Path) -> None:
    client = _client(tmp_path, None)
    assert client.get("/api/memory/list", params={"group_id": "mem_1_hiro"}).json() == {
        "memory_enabled": False,
        "memories": [],
    }
    assert client.post("/api/memory/delete", json={"ids": ["x"]}).status_code == 400


def test_memory_writes_reach_the_store(tmp_path: Path) -> None:
    memory = _FakeMemory()
    client = _client(tmp_path, memory)
    assert client.post("/api/memory/delete", json={"ids": ["x", " ", "y"]}).json() == {"deleted_count": 2}
    assert client.post("/api/memory/clear-group", json={"group_id": "eval_mem_adam"}).json() == {
        "deleted_count": 3
    }
    assert memory.calls == [("delete_many", ["x", "y"]), ("clear_groups", ["eval_mem_adam"])]


def test_chunk_hooks(tmp_path: Path) -> None:
    async def details(_request: Any, path: Path, ids: list[str]) -> list[dict[str, Any]]:
        return [{"id": i, "path": str(path)} for i in ids]

    async def search(_request: Any, _path: Path, text: str, limit: int) -> list[str]:
        return [f"{text}:{limit}"]

    plain = _client(tmp_path, _FakeMemory())
    # Defaults: Kuzu text (nothing here) and no search.
    assert plain.post("/api/knowledge/graph/chunks-detail", json={"chunk_ids": ["c1"]}).json() == {"chunks": []}
    assert plain.post("/api/knowledge/graph/search-chunks", json={"text": "x"}).json() == {"point_ids": []}

    hooked = _client(tmp_path, _FakeMemory(), chunk_details=details, search_chunks=search)
    assert hooked.post("/api/knowledge/graph/chunks-detail", json={"chunk_ids": ["c1", ""]}).json() == {
        "chunks": [{"id": "c1", "path": str(tmp_path)}]
    }
    assert hooked.post("/api/knowledge/graph/search-chunks", json={"text": "x", "limit": 9999}).json() == {
        "point_ids": ["x:500"]  # the scan is capped
    }


def test_sort_memories_handles_odd_dates() -> None:
    rows = [{"id": "old", "created_at": "0001-01-01T00:00:00"}, {"id": "new", "updated_at": 1_800_000_000_000}]
    assert [r["id"] for r in sort_memories(rows)] == ["new", "old"]
