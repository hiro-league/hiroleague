"""Tests for :class:`GraphIngestService` — the F7 write-gate + end-to-end orchestration.

The extractor is monkeypatched to return canned :class:`ExtractionResult`s so
these tests run without a real LLM. The resolver + store are real (Ladybug on a
temp file) — what's exercised is the gate, the per-chunk loop, the edge upserts,
and the stats reporting.
"""

from __future__ import annotations

import pytest

ladybug = pytest.importorskip("ladybug")
rapidfuzz = pytest.importorskip("rapidfuzz")

from .extractor import ExtractionResult, ExtractionUsage  # noqa: E402
from .ingest import (  # noqa: E402
    ALLOWED_SOURCE_ROLES,
    REJECTED_SOURCE_ROLES,
    ChunkInput,
    GraphIngestService,
)
from .ladybug_adapter import LadybugGraphStore  # noqa: E402
from .ontology import ChunkExtraction, ExtractedEntity, ExtractedRelation  # noqa: E402


# Decorate each async test individually with ``@pytest.mark.asyncio`` rather
# than module-level ``pytestmark`` — keeps the sync sanity test at the bottom
# clean without warnings from the asyncio plugin.


# ---------------------------------------------------------------------------
# Test scaffolding
# ---------------------------------------------------------------------------


class FakeChatModel:
    """Placeholder model object — the monkeypatched extractor never inspects it,
    but the service signature requires a non-None ``BaseChatModel``-like value."""


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "graph" / "ladybug.db"
    s = LadybugGraphStore.open(db_path)
    try:
        yield s
    finally:
        s.close()


def _canned_extraction(
    entities: list[tuple[str, str]] | None = None,
    relations: list[tuple[str, str, str]] | None = None,
    usage: ExtractionUsage | None = None,
) -> ExtractionResult:
    """Build an ExtractionResult from a compact spec — used to script the fake
    extractor without writing ChunkExtraction(...) boilerplate everywhere."""
    ents = [ExtractedEntity(name=n, type=t) for n, t in (entities or [])]
    rels = [
        ExtractedRelation(source_name=s, target_name=t, rel_type=r)
        for s, t, r in (relations or [])
    ]
    return ExtractionResult(
        extraction=ChunkExtraction(entities=ents, relations=rels),
        usage=usage or ExtractionUsage(input_tokens=100, output_tokens=50),
    )


def _patch_extractor(monkeypatch, script: list[ExtractionResult]) -> list[str]:
    """Replace ``extract_from_chunk`` with a fake that returns canned results
    in order. Returns a mutable list capturing the chunk texts the extractor
    saw, in call order."""
    calls: list[str] = []

    async def fake_extract(chunk_text, *, model):  # noqa: ANN001 — signature mirrors real fn
        calls.append(chunk_text)
        if not script:
            return _canned_extraction()
        return script.pop(0)

    monkeypatch.setattr(
        "hirocli.services.knowledge.graph.ingest.extract_from_chunk", fake_extract
    )
    return calls


# ---------------------------------------------------------------------------
# F7 — write-gate (the bleed-prevention invariant)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_gate_rejects_retrieved_knowledge(store, monkeypatch) -> None:
    """The exact mem0 #4573 failure mode: retrieved knowledge must NEVER be
    re-extracted into the graph. The gate triggers BEFORE the extractor — no
    LLM call should fire."""
    calls = _patch_extractor(monkeypatch, [_canned_extraction([("Maya", "Person")])])
    svc = GraphIngestService(store)
    chunks = [ChunkInput(chunk_id="c_1", document_id="d_1", text="Maya called.")]
    stats = await svc.ingest_chunks(
        chunks, source_role="retrieved_knowledge", model=FakeChatModel()
    )
    assert stats.chunks_received == 1
    assert stats.chunks_processed == 0
    assert stats.chunks_rejected == 1
    assert stats.rejected_roles == ["retrieved_knowledge"]
    assert calls == []  # cost guarantee: extractor never invoked
    # Graph is untouched
    assert store.find_by_name_exact("maya") == []


@pytest.mark.asyncio
async def test_write_gate_rejects_unknown_role(store, monkeypatch) -> None:
    """Allow-list semantics: any role not in ALLOWED is rejected (safer default
    than a deny-list — a forgotten tag fails closed, not open)."""
    calls = _patch_extractor(monkeypatch, [])
    svc = GraphIngestService(store)
    stats = await svc.ingest_chunks(
        [ChunkInput(chunk_id="c", document_id="d", text="x")],
        source_role="some_new_source",
        model=FakeChatModel(),
    )
    assert stats.chunks_rejected == 1
    assert calls == []


@pytest.mark.asyncio
async def test_write_gate_allows_user_document(store, monkeypatch) -> None:
    calls = _patch_extractor(monkeypatch, [_canned_extraction([("Maya", "Person")])])
    svc = GraphIngestService(store)
    stats = await svc.ingest_chunks(
        [ChunkInput(chunk_id="c_1", document_id="d_1", text="Maya called.")],
        source_role="user_document",
        model=FakeChatModel(),
    )
    assert stats.chunks_received == 1
    assert stats.chunks_processed == 1
    assert stats.chunks_rejected == 0
    assert calls == ["Maya called."]


# ---------------------------------------------------------------------------
# Happy path — the Example A shape lands in the graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_ingest_writes_entities_and_edges(store, monkeypatch) -> None:
    """Example A from the plan: one chunk → 5 typed entities + 5 typed edges,
    all with the chunk_id in their provenance. No LLM resolver calls expected
    (every entity is novel; deterministic create path)."""
    extraction = _canned_extraction(
        entities=[
            ("Maya", "Person"),
            ("Selim", "Person"),
            ("Paris", "Place"),
            ("Eiffel Tower", "Place"),
            ("Trip_2025_07", "Event"),
        ],
        relations=[
            ("Trip_2025_07", "Maya", "PARTICIPANT"),
            ("Trip_2025_07", "Selim", "PARTICIPANT"),
            ("Trip_2025_07", "Paris", "LOCATED_IN"),
            ("Maya", "Eiffel Tower", "STAYED_NEAR"),
        ],
    )
    _patch_extractor(monkeypatch, [extraction])
    svc = GraphIngestService(store)
    stats = await svc.ingest_chunks(
        [ChunkInput(chunk_id="c_42", document_id="d_07", text="...")],
        source_role="user_document",
        model=FakeChatModel(),
    )
    assert stats.chunks_processed == 1
    assert stats.entities_created == 5
    assert stats.entities_linked_exact == 0
    assert stats.entities_linked_llm == 0
    assert stats.edges_written == 4
    assert stats.llm_extraction_calls == 1
    assert stats.llm_disambiguation_calls == 0  # cost guarantee on fresh corpus

    # Spot-check provenance on a couple of nodes.
    [maya] = store.find_by_name_exact("maya")
    assert maya.type == "Person"
    assert "c_42" in maya.chunk_ids
    assert "d_07" in maya.document_ids

    [trip] = store.find_by_name_exact("trip_2025_07")
    assert trip.type == "Event"

    # The 4 edges are reachable from Trip_2025_07 (3) and Maya (1).
    out_from_trip = store.edges(trip.id, direction="out")
    assert {e.rel_type for e in out_from_trip} == {"PARTICIPANT", "LOCATED_IN"}


@pytest.mark.asyncio
async def test_repeat_ingest_is_idempotent(store, monkeypatch) -> None:
    """Re-ingesting the SAME chunk twice must NOT duplicate entities or edges —
    deterministic edge ids + provenance merge make this safe (F5 + LightRAG
    content-hash-as-join pattern)."""
    extraction = _canned_extraction(
        entities=[("Maya", "Person"), ("Paris", "Place")],
        relations=[("Maya", "Paris", "VISITED")],
    )
    _patch_extractor(
        monkeypatch,
        [
            # Same extraction twice — but each call needs its own object because
            # the fake pops from the list.
            _canned_extraction(
                entities=[("Maya", "Person"), ("Paris", "Place")],
                relations=[("Maya", "Paris", "VISITED")],
            ),
            _canned_extraction(
                entities=[("Maya", "Person"), ("Paris", "Place")],
                relations=[("Maya", "Paris", "VISITED")],
            ),
        ],
    )
    svc = GraphIngestService(store)
    chunk = ChunkInput(chunk_id="c_1", document_id="d_1", text="...")
    await svc.ingest_chunks([chunk], source_role="user_document", model=FakeChatModel())
    stats2 = await svc.ingest_chunks([chunk], source_role="user_document", model=FakeChatModel())

    # Second pass: every mention is exact_link, NOT created.
    assert stats2.entities_created == 0
    assert stats2.entities_linked_exact == 2

    # Still exactly one Maya, one Paris, one VISITED edge.
    assert len([n for n in store.find_by_name_exact("maya")]) == 1
    [maya] = store.find_by_name_exact("maya")
    visited = [e for e in store.edges(maya.id, direction="out") if e.rel_type == "VISITED"]
    assert len(visited) == 1
    # Provenance c_1 is present (deduped — no double "c_1" entry).
    assert visited[0].chunk_ids.count("c_1") == 1


@pytest.mark.asyncio
async def test_orphan_relations_are_dropped(store, monkeypatch) -> None:
    """If the extractor emits a relation whose endpoint isn't in entities[] (the
    extractor's own cleanup is the first line of defense; the service is the
    second), the relation must be DROPPED, never written with a missing endpoint."""
    extraction = ExtractionResult(
        extraction=ChunkExtraction(
            entities=[ExtractedEntity(name="Maya", type="Person")],
            # Bypass the extractor's cleanup by hand-crafting an orphan rel —
            # in production the extractor would strip this, but the service
            # must defend in depth (general-coding rule: don't trust upstream).
            relations=[
                ExtractedRelation(
                    source_name="Maya", target_name="Ghost", rel_type="KNOWS"
                ),
            ],
        ),
        usage=ExtractionUsage(),
    )
    _patch_extractor(monkeypatch, [extraction])
    svc = GraphIngestService(store)
    stats = await svc.ingest_chunks(
        [ChunkInput(chunk_id="c", document_id="d", text="x")],
        source_role="user_document",
        model=FakeChatModel(),
    )
    assert stats.edges_written == 0
    assert stats.edges_dropped_orphan == 1


@pytest.mark.asyncio
async def test_extraction_failure_is_counted_and_continues(
    store, monkeypatch
) -> None:
    """A chunk whose extractor errored (parsing_error set, empty extraction)
    must still be counted as processed — the LLM was paid for — and the next
    chunk must still run."""
    bad = ExtractionResult(
        extraction=ChunkExtraction(),
        usage=ExtractionUsage(parsing_error="boom"),
    )
    good = _canned_extraction([("Lina", "Person")])
    _patch_extractor(monkeypatch, [bad, good])
    svc = GraphIngestService(store)
    stats = await svc.ingest_chunks(
        [
            ChunkInput(chunk_id="c1", document_id="d", text="bad"),
            ChunkInput(chunk_id="c2", document_id="d", text="good"),
        ],
        source_role="user_document",
        model=FakeChatModel(),
    )
    assert stats.chunks_received == 2
    assert stats.chunks_processed == 2  # both counted as work-attempted
    assert stats.chunks_extraction_failed == 1
    assert stats.entities_created == 1  # only the good chunk produced an entity
    assert stats.llm_extraction_calls == 2


@pytest.mark.asyncio
async def test_empty_chunks_short_circuit(store, monkeypatch) -> None:
    """Empty input — service must not require a model (caller may have nothing
    to ingest); no extraction calls; no rejection."""
    calls = _patch_extractor(monkeypatch, [])
    svc = GraphIngestService(store)
    stats = await svc.ingest_chunks([], source_role="user_document", model=None)
    assert stats.chunks_received == 0
    assert stats.chunks_processed == 0
    assert stats.chunks_rejected == 0
    assert calls == []


@pytest.mark.asyncio
async def test_model_required_when_chunks_present(store, monkeypatch) -> None:
    """Defensive: model=None with non-empty chunks must fail loudly, not silently."""
    _patch_extractor(monkeypatch, [])
    svc = GraphIngestService(store)
    with pytest.raises(ValueError):
        await svc.ingest_chunks(
            [ChunkInput(chunk_id="c", document_id="d", text="x")],
            source_role="user_document",
            model=None,
        )


def test_allowed_and_rejected_roles_documentation() -> None:
    """Both constants are exported and documented. The allow-list is the source
    of truth; REJECTED is documentation for readers."""
    assert "user_document" in ALLOWED_SOURCE_ROLES
    assert "retrieved_knowledge" in REJECTED_SOURCE_ROLES
    assert "assistant_output" in REJECTED_SOURCE_ROLES
    assert "system" in REJECTED_SOURCE_ROLES
