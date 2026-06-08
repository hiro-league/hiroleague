"""Bootstrap tests for GraphitiMemoryService.

Exercises REAL Graphiti + Kuzu construction and ``build_indices_and_constraints``
against a temp DB (no network). The LLM/embedder are stubs that assert they are
never called during bootstrap/init — only the driver should be touched.
"""

from __future__ import annotations

import typing
from types import SimpleNamespace

import pytest
from graphiti_core.embedder.client import EmbedderClient
from graphiti_core.llm_client.client import LLMClient
from graphiti_core.llm_client.config import LLMConfig, ModelSize
from graphiti_core.prompts.models import Message
from pydantic import BaseModel

from hirocli.domain.preferences import WorkspacePreferences
from hirocli.services.knowledge.graph import kuzu_registry
from hirocli.services.knowledge.graph.graphiti_service import (
    GraphitiMemoryService,
    _registry_key,
    graphiti_db_path,
    is_kuzu_lock_error,
    read_graph_snapshot,
)


class _StubLLM(LLMClient):
    def __init__(self) -> None:
        super().__init__(LLMConfig())

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = 1024,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, typing.Any]:
        raise AssertionError("LLM must not be called during bootstrap/init")


class _StubEmbedder(EmbedderClient):
    async def create(self, input_data: typing.Any) -> list[float]:
        raise AssertionError("embedder must not be called during bootstrap/init")


@pytest.mark.asyncio
async def test_bootstrap_initializes_against_real_kuzu(tmp_path) -> None:
    db = graphiti_db_path(tmp_path)
    svc = GraphitiMemoryService(db_path=db, llm_client=_StubLLM(), embedder=_StubEmbedder())
    try:
        await svc.initialize()
        assert svc.graphiti is not None
        assert db.parent.exists()  # workspace/knowledge/graph/ created
        # initialize is idempotent
        await svc.initialize()
    finally:
        await svc.close()
    # close is idempotent
    await svc.close()


def test_from_preferences_none_when_backend_off(tmp_path) -> None:
    prefs = WorkspacePreferences()  # backend defaults to "off"
    assert GraphitiMemoryService.from_preferences(prefs, tmp_path) is None


def test_from_preferences_none_when_no_model(tmp_path) -> None:
    prefs = WorkspacePreferences()
    prefs.graph.backend = "graphiti"
    # No llm.default_chat and no knowledge.answering.model → extraction resolves
    # None (before any catalog/credential lookup) → service not created.
    assert GraphitiMemoryService.from_preferences(prefs, tmp_path, workspace_id="w") is None


@pytest.mark.asyncio
async def test_snapshot_empty_when_no_db(tmp_path) -> None:
    # No graph built → empty, and no DB file created (read must not have side effects).
    db = graphiti_db_path(tmp_path)
    nodes, edges, chunk_to_document = await read_graph_snapshot(db)
    assert nodes == []
    assert edges == []
    assert chunk_to_document == {}
    assert not db.exists()


@pytest.mark.asyncio
async def test_snapshot_empty_graph_against_real_kuzu(tmp_path) -> None:
    # Build an empty graph (schema only), then snapshot → empty lists. Validates the
    # EntityNode/EntityEdge.get_by_group_ids read path against real Kuzu.
    db = graphiti_db_path(tmp_path)
    svc = GraphitiMemoryService(db_path=db, llm_client=_StubLLM(), embedder=_StubEmbedder())
    try:
        await svc.initialize()
    finally:
        await svc.close()
    nodes, edges, _chunk_to_document = await read_graph_snapshot(db)
    assert nodes == []
    assert edges == []


# --- Shared-Database registry: the kuzu_issue.md regression + sharing/refcount ---


@pytest.mark.asyncio
async def test_snapshot_while_service_open_shares_driver(tmp_path) -> None:
    """Regression for docs/kuzu_issue.md: reading the Graph snapshot WHILE a service
    holds the graph open used to throw "Could not set lock on file" (a 2nd Database).
    Now every consumer shares ONE driver, so the snapshot succeeds mid-hold and the
    registry refcount returns to 1 after it."""
    db = graphiti_db_path(tmp_path)
    key = _registry_key(db)
    svc = GraphitiMemoryService(db_path=db, llm_client=_StubLLM(), embedder=_StubEmbedder())
    try:
        await svc.initialize()
        assert kuzu_registry._refcount(key) == 1
        # Service still open (driver held) → snapshot must NOT raise a lock error.
        nodes, edges, _ = await read_graph_snapshot(db)
        assert nodes == [] and edges == []
        # Snapshot reused the shared driver and released it → back to just the service.
        assert kuzu_registry._refcount(key) == 1
    finally:
        await svc.close()
    assert kuzu_registry._active_keys() == []  # last release freed the file lock


@pytest.mark.asyncio
async def test_snapshot_reads_on_dedicated_connection(tmp_path) -> None:
    """3b (docs/kuzu-shared-database-design.md §8, option b): the snapshot reads on its
    OWN AsyncConnection over the shared Database, so it must NOT touch the shared writer
    driver's ``client``. Guards against regressing to a shared-client swap (which would
    re-introduce read/write head-of-line blocking on the writer's pool=1 connection)."""
    db = graphiti_db_path(tmp_path)
    svc = GraphitiMemoryService(db_path=db, llm_client=_StubLLM(), embedder=_StubEmbedder())
    try:
        await svc.initialize()
        writer_client = svc.graphiti.driver.client  # the pinned pool=1 writer connection
        nodes, edges, _ = await read_graph_snapshot(db)
        assert nodes == [] and edges == []
        # The writer's connection object is untouched — the snapshot used its own.
        assert svc.graphiti.driver.client is writer_client
    finally:
        await svc.close()
    assert kuzu_registry._active_keys() == []


@pytest.mark.asyncio
async def test_two_services_same_path_share_one_driver(tmp_path) -> None:
    db = graphiti_db_path(tmp_path)
    key = _registry_key(db)
    a = GraphitiMemoryService(db_path=db, llm_client=_StubLLM(), embedder=_StubEmbedder())
    b = GraphitiMemoryService(db_path=db, llm_client=_StubLLM(), embedder=_StubEmbedder())
    try:
        # ONE shared kuzu.Database → the exact same driver object behind both services.
        assert a.graphiti.driver is b.graphiti.driver
        assert kuzu_registry._refcount(key) == 2
    finally:
        await a.close()
        assert kuzu_registry._refcount(key) == 1  # b still holds it → driver alive
        await b.close()
    assert kuzu_registry._active_keys() == []


def test_is_kuzu_lock_error_predicate() -> None:
    assert is_kuzu_lock_error(RuntimeError("IO exception: Could not set lock on file X"))
    assert not is_kuzu_lock_error(RuntimeError("some unrelated failure"))


@pytest.mark.asyncio
async def test_remove_episodes_skips_missing_ids(tmp_path) -> None:
    """The eval-reset primitive: removing ids absent from the graph (first run /
    partial prior run) is a no-op, not an error — ``remove_episode``'s
    NodeNotFoundError is swallowed and the returned count reflects only real
    deletions. Runs against an empty real Kuzu graph (no LLM/embedder needed)."""
    db = graphiti_db_path(tmp_path)
    svc = GraphitiMemoryService(db_path=db, llm_client=_StubLLM(), embedder=_StubEmbedder())
    try:
        removed = await svc.remove_episodes(["does-not-exist-1", "does-not-exist-2"])
    finally:
        await svc.close()
    assert removed == 0


@pytest.mark.asyncio
async def test_remove_episodes_by_document_scopes_by_source_description(
    tmp_path, monkeypatch
) -> None:
    """Scope-based wipe: filters the group's episodes by ``source_description ==
    document_id`` (the field ingest stamps), pages through them, and delegates ONLY
    the matched uuids to ``remove_episodes`` — independent of any corpus file. Guards
    the eval-reset bug where the graph wipe was keyed off the current file's ids and
    stranded a prior, larger run's episodes.

    The graph read/delete primitives are stubbed so the filtering/paging/delegation
    logic is tested without Kuzu writes (raw ``node.save`` in-test segfaults Kuzu's
    native teardown on Windows; the real read/delete paths run constantly in ingest)."""
    from types import SimpleNamespace

    from graphiti_core.nodes import EpisodicNode

    from hirocli.services.knowledge.graph import graphiti_service as gsvc_mod

    db = graphiti_db_path(tmp_path)
    svc = GraphitiMemoryService(db_path=db, llm_client=_StubLLM(), embedder=_StubEmbedder())

    # Two pages of 2: forces the uuid_cursor paging loop, with docA/docB interleaved
    # across the page boundary so a single-page read would miss "a3".
    pages = [
        [
            SimpleNamespace(uuid="a1", source_description="docA"),
            SimpleNamespace(uuid="b1", source_description="docB"),
        ],
        [
            SimpleNamespace(uuid="a3", source_description="docA"),
        ],
    ]

    async def _fake_get(cls, driver, group_ids, limit=None, uuid_cursor=None):
        # First call (no cursor) → full page 0 (len == page → loop continues);
        # second call (cursor at page-0 tail) → page 1; then empty.
        if uuid_cursor is None:
            return list(pages[0])
        if uuid_cursor == "b1":
            return list(pages[1])
        return []

    # Shrink the page to 2 so page-0 fills exactly and the uuid_cursor loop fires.
    monkeypatch.setattr(gsvc_mod, "_EPISODE_WIPE_PAGE", 2)
    monkeypatch.setattr(EpisodicNode, "get_by_group_ids", classmethod(_fake_get))

    captured: list[str] = []

    async def _fake_remove(uuids):
        captured.extend(uuids)
        return len(uuids)

    monkeypatch.setattr(svc, "remove_episodes", _fake_remove)

    try:
        removed = await svc.remove_episodes_by_document("docA")
    finally:
        await svc.close()

    # Only docA across BOTH pages; docB skipped; cursor paging reached a3.
    assert captured == ["a1", "a3"]
    assert removed == 2


# --- memory Phase 2: group-scoped read/write primitives ---


@pytest.mark.asyncio
async def test_list_facts_and_group_ids_empty_graph(tmp_path) -> None:
    """On a freshly-built (schema-only) graph the memory read primitives return empty,
    not raise: ``list_facts`` (no edges → GroupsEdgesNotFoundError → []) and
    ``list_group_ids`` (DISTINCT over an empty Episodic table → []). Validates the real
    Kuzu read path on a dedicated connection."""
    db = graphiti_db_path(tmp_path)
    svc = GraphitiMemoryService(db_path=db, llm_client=_StubLLM(), embedder=_StubEmbedder())
    try:
        await svc.initialize()
        assert await svc.list_facts(["mem_1_aria"]) == []
        assert await svc.list_group_ids("mem_1_") == []
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_list_facts_no_db_file_is_empty(tmp_path) -> None:
    """No graph built → ``list_facts`` returns [] without creating the DB (read must have
    no side effects, like the snapshot)."""
    db = graphiti_db_path(tmp_path)
    svc = object.__new__(GraphitiMemoryService)
    svc._db_path = db  # type: ignore[attr-defined]
    assert await svc.list_facts(["mem_1_aria"]) == []
    assert await svc.list_group_ids("mem_1_") == []
    assert not db.exists()


@pytest.mark.asyncio
async def test_clear_group_uses_group_scoped_clear_data(tmp_path, monkeypatch) -> None:
    """``clear_group`` counts the group's episodes (for the metric) then delegates the wipe to
    graphiti's group-scoped Kuzu op ``driver.graph_ops.clear_data(group_ids=[...])`` — which
    deletes RelatesToNode_ + Entity + Episodic + Community for the group (no orphan fact nodes
    left). Critically it must be GROUP-SCOPED, not a whole-DB wipe. clear_data stubbed (no real
    Kuzu deletes)."""
    from graphiti_core.nodes import EpisodicNode

    from hirocli.services.knowledge.graph import graphiti_service as gsvc_mod

    db = graphiti_db_path(tmp_path)
    svc = GraphitiMemoryService(db_path=db, llm_client=_StubLLM(), embedder=_StubEmbedder())

    pages = [
        [SimpleNamespace(uuid="m1"), SimpleNamespace(uuid="m2")],
        [SimpleNamespace(uuid="m3")],
    ]

    async def _fake_get(cls, driver, group_ids, limit=None, uuid_cursor=None):
        if uuid_cursor is None:
            return list(pages[0])
        if uuid_cursor == "m2":
            return list(pages[1])
        return []

    monkeypatch.setattr(gsvc_mod, "_EPISODE_WIPE_PAGE", 2)
    monkeypatch.setattr(EpisodicNode, "get_by_group_ids", classmethod(_fake_get))

    await svc.initialize()  # so the real driver (and driver.graph_ops) exists to patch
    captured: dict[str, object] = {}

    async def _fake_clear(executor, group_ids=None):
        captured["group_ids"] = group_ids

    monkeypatch.setattr(svc._graphiti.driver.graph_ops, "clear_data", _fake_clear)

    try:
        removed = await svc.clear_group("mem_42_aria")
    finally:
        await svc.close()

    # GROUP-SCOPED wipe (never a whole-DB delete that would erase other groups).
    assert captured["group_ids"] == ["mem_42_aria"]
    assert removed == 3  # episode count reported for the caller's metric


@pytest.mark.asyncio
async def test_delete_facts_filters_blanks_and_delegates(tmp_path, monkeypatch) -> None:
    """``delete_facts`` drops blank ids and delegates the rest to
    ``EntityEdge.delete_by_uuids`` under the write lock. Empty input is a no-op."""
    from graphiti_core.edges import EntityEdge

    db = graphiti_db_path(tmp_path)
    svc = GraphitiMemoryService(db_path=db, llm_client=_StubLLM(), embedder=_StubEmbedder())

    captured: dict[str, list[str]] = {}

    async def _fake_delete(cls, driver, uuids):
        captured["uuids"] = list(uuids)

    monkeypatch.setattr(EntityEdge, "delete_by_uuids", classmethod(_fake_delete))

    try:
        assert await svc.delete_facts([]) == 0  # no-op
        n = await svc.delete_facts(["e1", "e2", ""])
    finally:
        await svc.close()

    assert captured["uuids"] == ["e1", "e2"]  # blank filtered out
    assert n == 2
