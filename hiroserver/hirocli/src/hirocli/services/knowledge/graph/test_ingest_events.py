"""Tests for the live-viz event sink on GraphIngestService (graph viz MVP).

A fake event sink captures ``(event_type, payload)`` tuples so we can assert the
ingest emits node/edge/progress events with the right ``is_new`` flag and DTO
shape — without a real LLM or the Domain Event Bus.
"""

from __future__ import annotations

from typing import Any

import pytest

from ..constants import (
    KNOWLEDGE_GRAPH_EDGE_UPSERTED,
    KNOWLEDGE_GRAPH_INGEST_PROGRESS,
    KNOWLEDGE_GRAPH_NODE_UPSERTED,
)
from .ontology import ChunkExtraction, ExtractedEntity, ExtractedRelation

ladybug = pytest.importorskip("ladybug")

# Every test here is async; mark at module level (strict asyncio mode needs an explicit marker —
# mirrors test_ingest_ledger.py).
pytestmark = pytest.mark.asyncio

from .ingest import ChunkInput, GraphIngestService  # noqa: E402
from .ladybug_adapter import LadybugGraphStore  # noqa: E402


class _FakeStructured:
    def __init__(self, results: list[ChunkExtraction]) -> None:
        self._results = list(results)
        self._i = 0

    async def ainvoke(self, _messages):  # noqa: ANN001
        result = self._results[min(self._i, len(self._results) - 1)]
        self._i += 1
        return {"parsed": result}


class _FakeModel:
    def __init__(self, results: list[ChunkExtraction]) -> None:
        self._structured = _FakeStructured(results)

    def with_structured_output(self, _schema, **_kwargs):  # noqa: ANN001
        return self._structured


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "graph" / "ladybug.db"
    s = LadybugGraphStore.open(db_path)
    try:
        yield s
    finally:
        s.close()


def _extraction() -> ChunkExtraction:
    return ChunkExtraction(
        entities=[
            ExtractedEntity(name="Maya", type="Person"),
            ExtractedEntity(name="Paris", type="Place"),
        ],
        relations=[
            ExtractedRelation(source_name="Maya", target_name="Paris", rel_type="VISITED"),
        ],
    )


def _chunk(text: str, cid: str = "c_1", did: str = "d_1") -> ChunkInput:
    return ChunkInput(chunk_id=cid, document_id=did, text=text)


async def test_event_sink_emits_new_nodes_edges_and_progress(store: LadybugGraphStore) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    svc = GraphIngestService(store, event_sink=lambda t, p: events.append((t, p)))

    await svc.ingest_chunks(
        [_chunk("Maya visited Paris.")],
        source_role="user_document",
        model=_FakeModel([_extraction()]),
    )

    nodes = [p for t, p in events if t == KNOWLEDGE_GRAPH_NODE_UPSERTED]
    edges = [p for t, p in events if t == KNOWLEDGE_GRAPH_EDGE_UPSERTED]
    progress = [p for t, p in events if t == KNOWLEDGE_GRAPH_INGEST_PROGRESS]

    assert len(nodes) == 2
    assert all(p["is_new"] for p in nodes)  # first sighting → pop
    names = {p["node"]["name"] for p in nodes}
    assert names == {"Maya", "Paris"}
    # DTO carries provenance for the side panel.
    assert all(p["node"]["chunk_ids"] == ["c_1"] for p in nodes)

    assert len(edges) == 1
    assert edges[0]["is_new"] is True
    assert edges[0]["edge"]["source"] and edges[0]["edge"]["target"]
    assert edges[0]["edge"]["rel_type"] == "VISITED"

    assert progress and progress[-1] == {
        "document_id": "d_1",
        "chunk_index": 1,
        "chunk_total": 1,
    }


async def test_event_sink_marks_reingest_as_not_new(store: LadybugGraphStore) -> None:
    captured: list[tuple[str, dict[str, Any]]] = []
    svc = GraphIngestService(store, event_sink=lambda t, p: captured.append((t, p)))

    # First pass creates everything.
    await svc.ingest_chunks(
        [_chunk("Maya visited Paris.", cid="c_1")],
        source_role="user_document",
        model=_FakeModel([_extraction()]),
    )
    captured.clear()

    # Second pass re-asserts the same entities/relation → merge, not create.
    await svc.ingest_chunks(
        [_chunk("Maya visited Paris.", cid="c_2")],
        source_role="user_document",
        model=_FakeModel([_extraction()]),
    )

    nodes = [p for t, p in captured if t == KNOWLEDGE_GRAPH_NODE_UPSERTED]
    edges = [p for t, p in captured if t == KNOWLEDGE_GRAPH_EDGE_UPSERTED]
    assert nodes and all(p["is_new"] is False for p in nodes)  # pulse, not pop
    assert edges and edges[0]["is_new"] is False


async def test_no_event_sink_is_silent(store: LadybugGraphStore) -> None:
    # Sanity: the default (no sink) path must still ingest without error.
    svc = GraphIngestService(store)
    stats = await svc.ingest_chunks(
        [_chunk("Maya visited Paris.")],
        source_role="user_document",
        model=_FakeModel([_extraction()]),
    )
    assert stats.entities_created == 2 and stats.edges_written == 1
