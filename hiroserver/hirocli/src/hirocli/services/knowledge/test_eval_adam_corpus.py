"""Tests for the Adam episode-corpus ingestion wiring (eval Phase 6).

Pure: a fake KnowledgeService records single-point upserts and a fake
GraphitiMemoryService (patched into ``from_preferences``) records the episodes —
no Qdrant, no model. Verifies the uuid mapping (episode id → shared point_id ==
Graphiti episode uuid) and the tagged Qdrant double-write over the real 35-episode
corpus.
"""

from __future__ import annotations

import uuid as _uuid

import pytest

import hirocli.services.knowledge.graph as graphpkg
from hirocli.services.knowledge.eval_runner import (
    ADAM_CORPUS_FILE,
    ADAM_EVAL_TAG,
    adam_point_id,
    ingest_adam_corpus_via_service,
)
from hirocli.services.knowledge.graph.graphiti_corpus import load_episodes_file


def test_adam_point_id_is_deterministic_uuid() -> None:
    a = adam_point_id("ep_001")
    b = adam_point_id("ep_001")
    c = adam_point_id("ep_002")
    assert a == b  # deterministic
    assert a != c  # distinct per episode
    _uuid.UUID(a)  # valid uuid (Qdrant requires uuid/int ids)


class _FakeVectorStore:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_document(self, document_id) -> None:
        self.deleted.append(document_id)


class _FakeService:
    def __init__(self) -> None:
        self.points: list[dict] = []
        self.vector_store = _FakeVectorStore()

    async def ingest_text_chunk(
        self, *, point_id, text, document_id, title="", tags=(), ord=1
    ) -> None:
        self.points.append(
            {"point_id": point_id, "text": text, "document_id": document_id, "tags": list(tags)}
        )


class _FakeGsvc:
    def __init__(self) -> None:
        self.ingested = None
        self.wiped_documents: list[str] = []

    async def remove_episodes_by_document(self, document_id) -> int:
        # Scope-based reset: the runner wipes the graph by document_id (not by the
        # current file's episode ids), so record what scope it asked us to clear.
        self.wiped_documents.append(document_id)
        return 0

    async def ingest_chunks(self, episodes, *, source_role, event_sink=None, ledger_sink=None):
        self.ingested = list(episodes)

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_ingest_adam_corpus_double_writes(tmp_path, monkeypatch) -> None:
    svc = _FakeService()
    gsvc = _FakeGsvc()
    monkeypatch.setattr(
        graphpkg.GraphitiMemoryService,
        "from_preferences",
        classmethod(lambda cls, prefs, ws, **kw: gsvc),
    )

    # Derive the expected count from the corpus file itself so the test is robust to
    # a locally-truncated corpus (a smaller test run) — it asserts the wiring, not a
    # fixed episode count.
    expected = len(load_episodes_file(ADAM_CORPUS_FILE))
    n = await ingest_adam_corpus_via_service(svc, tmp_path)

    assert n == expected
    assert len(svc.points) == expected
    for p in svc.points:
        _uuid.UUID(p["point_id"])  # valid uuid
        assert ADAM_EVAL_TAG in p["tags"]

    # Reset is scope-based: the graph + vector wipe target the document_id, NOT the
    # current file's per-episode ids (so a prior, larger run is fully cleared).
    assert svc.vector_store.deleted == ["adam_year"]
    assert gsvc.wiped_documents == ["adam_year"]

    # Graphiti episodes reuse the SAME uuid as their Qdrant point_id (the join key).
    assert gsvc.ingested is not None
    assert len(gsvc.ingested) == expected
    qdrant_ids = {p["point_id"] for p in svc.points}
    graph_ids = {e.chunk_id for e in gsvc.ingested}
    assert qdrant_ids == graph_ids


@pytest.mark.asyncio
async def test_ingest_adam_corpus_raises_when_no_graph_model(tmp_path, monkeypatch) -> None:
    svc = _FakeService()
    # from_preferences returns None (backend off / no model) → graph build can't run.
    monkeypatch.setattr(
        graphpkg.GraphitiMemoryService,
        "from_preferences",
        classmethod(lambda cls, prefs, ws, **kw: None),
    )
    with pytest.raises(RuntimeError, match="no extraction model"):
        await ingest_adam_corpus_via_service(svc, tmp_path)
