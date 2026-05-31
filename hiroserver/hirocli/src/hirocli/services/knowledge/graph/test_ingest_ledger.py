"""Tests for the L3 graph-ingest ledger trace.

Verifies that with a sink wired in, ``GraphIngestService.ingest_chunks`` writes:

  * one per-chunk row per step: ``knowledge_graph_ingest/extract``,
    ``.../resolve``, ``.../write`` (option B granularity per the plan)
  * one aggregate ``@run`` row carrying counts + status

Approach: monkeypatch ``LedgerSink.write_rows`` to capture every row written
during the run, then assert on row decisions / previews / node names. This
exercises the real ledger pipeline without depending on log-file flush timing.
"""

from __future__ import annotations

import pytest

ladybug = pytest.importorskip("ladybug")
rapidfuzz = pytest.importorskip("rapidfuzz")

from hirocli.runtime.agent_graph.ledger import LedgerSink  # noqa: E402

from .extractor import ExtractionResult, ExtractionUsage  # noqa: E402
from .ingest import ChunkInput, GraphIngestService  # noqa: E402
from .ingest_ledger import (  # noqa: E402
    GRAPH_INGEST_NODE_PREFIX,
    format_resolution_preview,
    preview_ingest_input,
    preview_ingest_output,
)
from .ladybug_adapter import LadybugGraphStore  # noqa: E402
from .ontology import ChunkExtraction, ExtractedEntity, ExtractedRelation  # noqa: E402


# ---------------------------------------------------------------------------
# Scaffolding — capture every row the sink would have written
# ---------------------------------------------------------------------------


class _CapturingSink(LedgerSink):
    """LedgerSink that diverts ``write_rows`` into an in-memory list.

    Real LedgerSink writes rows via a structured logger to ``logs/graph.log``.
    For tests we just want to see what *would* have been written; the logger
    side effects are irrelevant. Subclassing preserves all the entry-allocation
    logic (open_entry, step counters, run_id resolution) — only the persist
    step is intercepted."""

    def __init__(self, workspace_path):
        super().__init__(workspace_path)
        self.captured_rows: list[dict] = []

    def write_rows(self, rows):  # noqa: ANN001
        # Fold into RunAccumulator (matches parent behavior) so the @run row
        # reflects the real token totals — without this, the cost columns on
        # the aggregate row would always be 0.
        from hirocli.runtime.agent_graph.ledger import current_run, _row_kind

        for row in rows:
            priced = self._with_cost(row) if _row_kind(row) == "node" else row
            acc = current_run.get()
            if acc is not None:
                acc.fold_row(priced)
            self.captured_rows.append(dict(priced))


class FakeChatModel:
    """Placeholder — the patched extractor never inspects it."""


@pytest.fixture
def store_and_sink(tmp_path):
    """Open a real Ladybug store and a capturing sink rooted at the same workspace."""
    db_path = tmp_path / "knowledge" / "graph" / "ladybug.db"
    store = LadybugGraphStore.open(db_path)
    sink = _CapturingSink(tmp_path)
    try:
        yield store, sink, tmp_path
    finally:
        store.close()


def _patch_extractor(monkeypatch, script):
    """Stub extract_from_chunk with canned ExtractionResults (same trick as test_ingest)."""

    async def fake_extract(chunk_text, *, model):  # noqa: ANN001
        if not script:
            return ExtractionResult(extraction=ChunkExtraction(), usage=ExtractionUsage())
        return script.pop(0)

    monkeypatch.setattr(
        "hirocli.services.knowledge.graph.ingest.extract_from_chunk", fake_extract
    )


def _result(entities=(), relations=(), usage=None):
    ents = [ExtractedEntity(name=n, type=t) for n, t in entities]
    rels = [
        ExtractedRelation(source_name=s, target_name=t, rel_type=r)
        for s, t, r in relations
    ]
    return ExtractionResult(
        extraction=ChunkExtraction(entities=ents, relations=rels),
        usage=usage or ExtractionUsage(input_tokens=120, output_tokens=80),
    )


def _node_names(rows):
    return [r["node"] for r in rows]


# ---------------------------------------------------------------------------
# Pure helper tests — no async, no service
# ---------------------------------------------------------------------------


class _Stats:
    """Duck-type stand-in for GraphIngestStats — preview helpers are loose
    enough that we test them against this minimal shape, not the real class."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_preview_ingest_input_compact() -> None:
    out = preview_ingest_input(
        document_id="d_abcdefghijklm",
        document_title="trips.md",
        source_role="user_document",
        chunks_count=8,
    )
    assert "trips.md" in out and "user_document" in out and "8 chunk" in out


def test_preview_ingest_output_clean_run() -> None:
    out = preview_ingest_output(
        _Stats(
            chunks_received=2, chunks_processed=2, entities_linked_exact=3,
            entities_created=2, edges_written=4, llm_extraction_calls=2,
            llm_disambiguation_calls=0, total_input_tokens=240, total_output_tokens=160,
        )
    )
    assert "chunks=2/2" in out
    assert "ex3" in out and "ne2" in out and "edges=4" in out
    assert "2ext+0dis" in out
    assert "240i/160o" in out


def test_preview_ingest_output_with_rejections_and_errors() -> None:
    out = preview_ingest_output(
        _Stats(
            chunks_received=3, chunks_processed=0, chunks_rejected=3,
            chunks_extraction_failed=0, entities_created=0, edges_written=0,
            llm_extraction_calls=0, llm_disambiguation_calls=0,
            total_input_tokens=0, total_output_tokens=0, edges_dropped_orphan=0,
        )
    )
    assert "rej=3" in out


def test_format_resolution_preview_truncates() -> None:
    rs = [
        ("Maya", "exact_link", "p_maya"),
        ("Selim", "exact_link", "p_selim"),
        ("Paris", "created", "place_paris"),
        ("Eiffel Tower", "created", "place_eiffel"),
        ("Trip_2025_07", "created", "ev_2025_07"),
        ("Sara", "fuzzy_link", "p_sara"),
        ("Mom", "llm_link", "p_sara"),
    ]
    out = format_resolution_preview(rs, limit=4)
    assert "Maya→exact" in out
    assert "(+3 more)" in out


def test_format_resolution_preview_empty() -> None:
    assert format_resolution_preview([]) == "no mentions"


# ---------------------------------------------------------------------------
# End-to-end ledger trace tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_ingest_emits_three_rows_per_chunk_plus_run(
    store_and_sink, monkeypatch
) -> None:
    """Example A: 1 chunk → extract + resolve + write = 3 node rows, then
    one aggregate @run row. Decisions/previews carry the real shape."""
    store, sink, workspace = store_and_sink
    _patch_extractor(
        monkeypatch,
        [
            _result(
                entities=[
                    ("Maya", "Person"),
                    ("Selim", "Person"),
                    ("Paris", "Place"),
                ],
                relations=[("Maya", "Selim", "KNOWS"), ("Maya", "Paris", "VISITED")],
            )
        ],
    )

    svc = GraphIngestService(store, workspace_path=workspace)
    svc._sink = sink  # use the capturing sink instead of the real one

    stats = await svc.ingest_chunks(
        [ChunkInput(chunk_id="c_42", document_id="d_07", text="Maya...")],
        source_role="user_document",
        model=FakeChatModel(),
        document_id="d_07",
        document_title="trips.md",
    )

    nodes = _node_names(sink.captured_rows)
    # Three per-chunk node rows + one aggregate run row
    assert nodes.count(f"{GRAPH_INGEST_NODE_PREFIX}/extract") == 1
    assert nodes.count(f"{GRAPH_INGEST_NODE_PREFIX}/resolve") == 1
    assert nodes.count(f"{GRAPH_INGEST_NODE_PREFIX}/write") == 1
    assert nodes.count("@run") == 1

    # Extract row carries the real token usage (captures={"usage"}).
    extract_row = next(r for r in sink.captured_rows if r["node"].endswith("/extract"))
    assert extract_row["input_tokens"] == 120
    assert extract_row["output_tokens"] == 80
    assert extract_row["decision_kind"] == "extracted"
    assert "Maya" in extract_row["output_preview"]

    # Resolve row records branch counts in decision_detail + per-mention preview.
    resolve_row = next(r for r in sink.captured_rows if r["node"].endswith("/resolve"))
    assert resolve_row["decision_kind"] == "resolved"
    assert "created" in resolve_row["decision_detail"]
    assert "Maya" in resolve_row["output_preview"]

    # Write row records edge counts.
    write_row = next(r for r in sink.captured_rows if r["node"].endswith("/write"))
    assert write_row["decision_kind"] == "wrote"
    assert "n3_e2" in write_row["decision_detail"]

    # Aggregate run row reflects success + the input/output preview shape.
    run_row = next(r for r in sink.captured_rows if r["node"] == "@run")
    assert run_row["status"] == "completed"
    assert run_row["decision_detail"] == "graph_ingest"
    assert "trips.md" in run_row["input_preview"]
    # Token totals folded from the extract row into the run accumulator.
    assert run_row["input_tokens"] == 120
    assert run_row["output_tokens"] == 80
    assert stats.chunks_processed == 1


@pytest.mark.asyncio
async def test_two_chunks_produce_six_node_rows_in_order(
    store_and_sink, monkeypatch
) -> None:
    """Per-chunk rows interleave in the natural extract/resolve/write order."""
    store, sink, workspace = store_and_sink
    _patch_extractor(
        monkeypatch,
        [
            _result(entities=[("Lina", "Person")]),
            _result(entities=[("Omar", "Person")]),
        ],
    )

    svc = GraphIngestService(store, workspace_path=workspace)
    svc._sink = sink

    await svc.ingest_chunks(
        [
            ChunkInput(chunk_id="c1", document_id="d", text="lina"),
            ChunkInput(chunk_id="c2", document_id="d", text="omar"),
        ],
        source_role="user_document",
        model=FakeChatModel(),
        document_id="d",
    )

    node_rows = [
        r for r in sink.captured_rows if r["node"].startswith(GRAPH_INGEST_NODE_PREFIX)
    ]
    assert [r["node"].rsplit("/", 1)[-1] for r in node_rows] == [
        "extract", "resolve", "write",  # chunk 1
        "extract", "resolve", "write",  # chunk 2
    ]


@pytest.mark.asyncio
async def test_write_gate_rejection_still_emits_run_row(
    store_and_sink, monkeypatch
) -> None:
    """F7 invariant + ledger invariant: rejected role → no per-chunk rows
    (extractor never invoked) BUT the @run row still lands, marked rejected,
    so a tail-the-log workflow sees the attempted ingest."""
    store, sink, workspace = store_and_sink
    _patch_extractor(monkeypatch, [])  # no canned results — must not be called

    svc = GraphIngestService(store, workspace_path=workspace)
    svc._sink = sink

    stats = await svc.ingest_chunks(
        [ChunkInput(chunk_id="c", document_id="d", text="x")],
        source_role="retrieved_knowledge",
        model=FakeChatModel(),
        document_id="d",
        document_title="bleed.md",
    )

    assert stats.chunks_rejected == 1
    # No per-chunk step rows — gate fires before any ledger_step opens.
    assert not any(
        r["node"].startswith(GRAPH_INGEST_NODE_PREFIX) for r in sink.captured_rows
    )
    # But the aggregate run row IS written, with status=rejected and the role tag.
    [run_row] = [r for r in sink.captured_rows if r["node"] == "@run"]
    assert run_row["status"] == "rejected"
    assert run_row["decision_detail"] == "rejected"
    assert "retrieved_knowledge" in run_row["input_preview"]


@pytest.mark.asyncio
async def test_extraction_failure_writes_error_row_and_continues(
    store_and_sink, monkeypatch
) -> None:
    """A parse-failed chunk yields an extract row marked error; later chunks
    still process; aggregate run row's decision_detail reflects the issue."""
    store, sink, workspace = store_and_sink
    bad = ExtractionResult(
        extraction=ChunkExtraction(), usage=ExtractionUsage(parsing_error="boom")
    )
    good = _result(entities=[("Lina", "Person")])
    _patch_extractor(monkeypatch, [bad, good])

    svc = GraphIngestService(store, workspace_path=workspace)
    svc._sink = sink

    await svc.ingest_chunks(
        [
            ChunkInput(chunk_id="c_bad", document_id="d", text="bad"),
            ChunkInput(chunk_id="c_good", document_id="d", text="good"),
        ],
        source_role="user_document",
        model=FakeChatModel(),
        document_id="d",
    )

    extract_rows = [
        r for r in sink.captured_rows if r["node"].endswith("/extract")
    ]
    assert len(extract_rows) == 2
    bad_row, good_row = extract_rows
    assert bad_row["status"] == "error"
    assert "extraction_failed" in bad_row["error_code"]
    assert good_row["status"] == "ok"
    assert good_row["decision_kind"] == "extracted"

    [run_row] = [r for r in sink.captured_rows if r["node"] == "@run"]
    assert run_row["decision_detail"] == "extraction_errors"


@pytest.mark.asyncio
async def test_empty_chunks_emits_only_run_row(store_and_sink, monkeypatch) -> None:
    """No work to do, but the run row still lands so the call is observable."""
    store, sink, workspace = store_and_sink
    _patch_extractor(monkeypatch, [])
    svc = GraphIngestService(store, workspace_path=workspace)
    svc._sink = sink

    await svc.ingest_chunks(
        [], source_role="user_document", model=None, document_id="d_empty"
    )

    assert [r["node"] for r in sink.captured_rows] == ["@run"]


@pytest.mark.asyncio
async def test_no_workspace_path_means_no_ledger_writes(
    tmp_path, monkeypatch
) -> None:
    """Backward-compat: when workspace_path is omitted, sink is None and the
    pipeline produces zero ledger rows. Existing test_ingest assertions rely
    on this (no_sink path)."""
    db_path = tmp_path / "graph" / "ladybug.db"
    store = LadybugGraphStore.open(db_path)
    try:
        _patch_extractor(monkeypatch, [_result(entities=[("Maya", "Person")])])
        svc = GraphIngestService(store)  # no workspace_path
        assert svc._sink is None
        await svc.ingest_chunks(
            [ChunkInput(chunk_id="c", document_id="d", text="x")],
            source_role="user_document",
            model=FakeChatModel(),
        )
        # Nothing to assert about rows — there's no sink. Just confirm no exception
        # and that the pipeline still wrote to the graph (regression smoke).
        assert store.find_by_name_exact("maya")
    finally:
        store.close()
