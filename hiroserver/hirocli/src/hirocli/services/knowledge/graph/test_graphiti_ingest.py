"""Tests for the Graphiti ingest mapping (chunk → episode).

Pure: a fake Graphiti client records ``add_episode`` kwargs and returns canned
results — no Kuzu, no network, no LLM. Verifies the F7 write-gate, episode param
mapping (uuid=chunk_id, source_description=document_id, EpisodeType), chronological
ordering, speaker prefixing, stats, and progress events. The delegation test
exercises ``GraphitiMemoryService.ingest_chunks`` without constructing real Kuzu.
"""

from __future__ import annotations

import datetime as dt

import pytest
from graphiti_core.nodes import EpisodeType

from hirocli.services.knowledge.constants import (
    KNOWLEDGE_GRAPH_EDGE_UPSERTED,
    KNOWLEDGE_GRAPH_INGEST_PROGRESS,
    KNOWLEDGE_GRAPH_NODE_UPSERTED,
)
from graphiti_core.nodes import EpisodicNode

from hirocli.services.knowledge.graph.graphiti_ingest import (
    GraphitiEpisodeInput,
    ingest_episodes,
)
from hirocli.services.knowledge.graph.graphiti_service import GraphitiMemoryService


class _Result:
    def __init__(self, nodes: int, edges: int) -> None:
        self.nodes = [object()] * nodes
        self.edges = [object()] * edges


class _FakeGraphiti:
    def __init__(self, nodes: int = 2, edges: int = 1) -> None:
        self.calls: list[dict] = []
        self._nodes = nodes
        self._edges = edges
        self.indices_built = 0

    async def add_episode(self, **kwargs) -> _Result:
        self.calls.append(kwargs)
        return _Result(self._nodes, self._edges)

    async def build_indices_and_constraints(self, delete_existing: bool = False) -> None:
        self.indices_built += 1

    async def close(self) -> None:  # pragma: no cover - trivial
        return None


def _ts(month: int) -> dt.datetime:
    return dt.datetime(2024, month, 1, tzinfo=dt.UTC)


@pytest.mark.asyncio
async def test_write_gate_rejects_non_user_document() -> None:
    g = _FakeGraphiti()
    eps = [GraphitiEpisodeInput(chunk_id="c1", document_id="d1", text="hi")]
    stats = await ingest_episodes(g, eps, source_role="retrieved_knowledge")
    assert g.calls == []
    assert stats.episodes_rejected == 1
    assert stats.episodes_processed == 0
    assert "retrieved_knowledge" in stats.rejected_roles


@pytest.mark.asyncio
async def test_maps_episode_params() -> None:
    g = _FakeGraphiti(nodes=3, edges=2)
    ts = dt.datetime(2024, 1, 15, 9, 0, 0, tzinfo=dt.UTC)
    types = {"Person": object}
    eps = [
        GraphitiEpisodeInput(
            chunk_id="pt-1",
            document_id="doc-A",
            text="Adam started at Brightloom.",
            reference_time=ts,
            document_title="Adam",
        )
    ]
    stats = await ingest_episodes(
        g, eps, source_role="user_document", group_id="grp", entity_types=types
    )
    assert len(g.calls) == 1
    call = g.calls[0]
    assert call["uuid"] == "pt-1"
    assert call["episode_body"] == "Adam started at Brightloom."
    assert call["source_description"] == "doc-A"
    assert call["reference_time"] == ts
    assert call["source"] == EpisodeType.text
    assert call["group_id"] == "grp"
    assert call["entity_types"] == types
    assert stats.episodes_processed == 1
    assert stats.entities_total == 3
    assert stats.edges_total == 2


@pytest.mark.asyncio
async def test_sorted_chronologically() -> None:
    g = _FakeGraphiti()
    eps = [
        GraphitiEpisodeInput(chunk_id="may", document_id="d", text="May", reference_time=_ts(5)),
        GraphitiEpisodeInput(chunk_id="aug", document_id="d", text="Aug", reference_time=_ts(8)),
        GraphitiEpisodeInput(chunk_id="jan", document_id="d", text="Jan", reference_time=_ts(1)),
    ]
    await ingest_episodes(g, eps, source_role="user_document")
    assert [c["uuid"] for c in g.calls] == ["jan", "may", "aug"]


@pytest.mark.asyncio
async def test_preseeds_episode_node_with_chunk_uuid(monkeypatch) -> None:
    """When the client exposes a real driver, the episode is pre-created with
    uuid=chunk_id BEFORE add_episode — so graphiti's get_by_uuid finds it (G6) instead
    of raising NodeNotFoundError. Guards the regression fixed for the Adam eval."""
    saved: list[dict] = []

    async def _fake_save(self, driver) -> None:  # noqa: ANN001
        saved.append({"uuid": self.uuid, "content": self.content, "group_id": self.group_id})

    monkeypatch.setattr(EpisodicNode, "save", _fake_save)

    g = _FakeGraphiti()
    g.driver = object()  # presence of a driver triggers the real-path pre-seed
    eps = [
        GraphitiEpisodeInput(
            chunk_id="pt-1", document_id="d1", text="hello", reference_time=_ts(1)
        )
    ]
    stats = await ingest_episodes(g, eps, source_role="user_document", group_id="grp")

    assert stats.episodes_processed == 1
    # Pre-seed happened with our point_id + content, BEFORE add_episode recorded its call.
    assert saved == [{"uuid": "pt-1", "content": "hello", "group_id": "grp"}]
    assert g.calls[0]["uuid"] == "pt-1"


@pytest.mark.asyncio
async def test_message_source_prefixes_speaker() -> None:
    g = _FakeGraphiti()
    eps = [
        GraphitiEpisodeInput(
            chunk_id="m1",
            document_id="chat",
            text="I left Brightloom!",
            source="message",
            speaker="Adam",
        )
    ]
    await ingest_episodes(g, eps, source_role="user_document")
    call = g.calls[0]
    assert call["source"] == EpisodeType.message
    assert call["episode_body"] == "Adam: I left Brightloom!"


@pytest.mark.asyncio
async def test_progress_events_emitted() -> None:
    g = _FakeGraphiti()
    events: list[tuple[str, dict]] = []
    eps = [
        GraphitiEpisodeInput(chunk_id=f"c{i}", document_id="d", text=str(i), reference_time=_ts(i + 1))
        for i in range(3)
    ]
    await ingest_episodes(
        g, eps, source_role="user_document", event_sink=lambda t, p: events.append((t, p))
    )
    progress = [p for (t, p) in events if t == KNOWLEDGE_GRAPH_INGEST_PROGRESS]
    assert len(progress) == 3
    assert progress[-1] == {"document_id": "d", "chunk_index": 3, "chunk_total": 3}


@pytest.mark.asyncio
async def test_node_edge_events_emitted() -> None:
    g = _FakeGraphiti(nodes=2, edges=1)
    events: list[tuple[str, dict]] = []
    eps = [GraphitiEpisodeInput(chunk_id="c1", document_id="d", text="hi")]
    await ingest_episodes(
        g, eps, source_role="user_document", event_sink=lambda t, p: events.append((t, p))
    )
    node_events = [p for (t, p) in events if t == KNOWLEDGE_GRAPH_NODE_UPSERTED]
    edge_events = [p for (t, p) in events if t == KNOWLEDGE_GRAPH_EDGE_UPSERTED]
    assert len(node_events) == 2
    assert len(edge_events) == 1
    assert node_events[0]["is_new"] is True
    assert node_events[0]["document_id"] == "d"
    assert "node" in node_events[0]
    assert "edge" in edge_events[0]


@pytest.mark.asyncio
async def test_empty_is_noop() -> None:
    g = _FakeGraphiti()
    stats = await ingest_episodes(g, [], source_role="user_document")
    assert g.calls == []
    assert stats.episodes_received == 0
    assert stats.episodes_processed == 0


@pytest.mark.asyncio
async def test_service_ingest_chunks_delegates_and_inits() -> None:
    # Bypass __init__ so no real Kuzu/Graphiti is constructed — we only test that
    # ingest_chunks auto-initializes and forwards to ingest_episodes with the
    # ontology + group_id.
    svc = object.__new__(GraphitiMemoryService)
    fake = _FakeGraphiti()
    svc._graphiti = fake  # type: ignore[attr-defined]
    svc._group_id = "grp"  # type: ignore[attr-defined]
    svc._initialized = False  # type: ignore[attr-defined]
    svc._closed = False  # type: ignore[attr-defined]
    svc._db_path = "test.db"  # type: ignore[attr-defined]  # only used in a log line
    svc._ledger_detail = "rich"  # type: ignore[attr-defined]

    stats = await svc.ingest_chunks(
        [GraphitiEpisodeInput(chunk_id="c1", document_id="d", text="hi")],
        source_role="user_document",
    )

    assert fake.indices_built == 1  # auto-initialized
    assert len(fake.calls) == 1
    assert fake.calls[0]["group_id"] == "grp"
    assert fake.calls[0]["entity_types"] is not None  # pinned ontology passed
    assert "Person" in fake.calls[0]["entity_types"]
    assert stats.episodes_processed == 1
