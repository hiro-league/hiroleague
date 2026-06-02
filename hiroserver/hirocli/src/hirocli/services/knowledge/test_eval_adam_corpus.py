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
    ADAM_EVAL_TAG,
    adam_point_id,
    ingest_adam_corpus_via_service,
)


def test_adam_point_id_is_deterministic_uuid() -> None:
    a = adam_point_id("ep_001")
    b = adam_point_id("ep_001")
    c = adam_point_id("ep_002")
    assert a == b  # deterministic
    assert a != c  # distinct per episode
    _uuid.UUID(a)  # valid uuid (Qdrant requires uuid/int ids)


class _FakeService:
    def __init__(self) -> None:
        self.points: list[dict] = []

    async def ingest_text_chunk(
        self, *, point_id, text, document_id, title="", tags=(), ord=1
    ) -> None:
        self.points.append(
            {"point_id": point_id, "text": text, "document_id": document_id, "tags": list(tags)}
        )


class _FakeGsvc:
    def __init__(self) -> None:
        self.ingested = None

    async def ingest_chunks(self, episodes, *, source_role):
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

    n = await ingest_adam_corpus_via_service(svc, tmp_path)

    assert n == 35
    assert len(svc.points) == 35
    for p in svc.points:
        _uuid.UUID(p["point_id"])  # valid uuid
        assert ADAM_EVAL_TAG in p["tags"]

    # Graphiti episodes reuse the SAME uuid as their Qdrant point_id (the join key).
    assert gsvc.ingested is not None
    assert len(gsvc.ingested) == 35
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
