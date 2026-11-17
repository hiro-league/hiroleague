"""``KnowledgeIndex``: ingest a file into a tmp collection (fake embedders, no network), read it back, retrieve it,
remove it; and the answer run around a graph (``answer.py``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hiro_memory.knowledge.answer import answer_result, answer_state, run_answer
from hiro_memory.knowledge.catalog_store import CatalogStore
from hiro_memory.knowledge.index import KnowledgeIndex
from hiro_memory.knowledge.settings import KnowledgeChunkingSettings
from hiro_memory.knowledge.vector_store import KnowledgeVectorStore
from hiro_memory.ledger import RunAccumulator, current_run
from hiro_memory.testing import RecordingLedgerSink


class _Dense:
    dimension = 4

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_texts(self, texts):
        self.calls.append(list(texts))
        return [[1.0, float(len(t) % 7), 0.5, 0.25] for t in texts]


class _Sparse:
    model_name = "fake-bm25"

    def embed_documents(self, texts):
        return [([1, 2], [1.0, 1.0]) for _ in texts]

    def embed_query(self, text):
        return ([1], [1.0])


def _index(tmp_path: Path) -> KnowledgeIndex:
    catalog = CatalogStore(tmp_path / "knowledge.db")
    catalog.ensure_schema()
    dense = _Dense()
    return KnowledgeIndex(catalog=catalog, vector_store=KnowledgeVectorStore(tmp_path / "qdrant", dense),
                          embedder=dense, sparse_embedder=_Sparse())


def _note(tmp_path: Path, text: str = "# Lemon tree\n\nWater the lemon tree every Tuesday.\n") -> Path:
    path = tmp_path / "docs" / "lemon.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_ingest_file_indexes_reads_back_and_skips_unchanged(tmp_path: Path) -> None:
    index = _index(tmp_path)
    note = _note(tmp_path)
    seen: list[tuple[str, str]] = []
    try:
        params = {"owner_kind": "system", "owner_id": "0", "tags": ["eval"]}
        chunks = await index.ingest_file(str(note), params, chunking=KnowledgeChunkingSettings(),
                                         max_file_size_bytes=10_000, on_ingested=lambda d, s: seen.append((d, s)))
        assert chunks == 1
        assert len(seen) == 1 and seen[0][1] == str(note.resolve())
        document_id = seen[0][0]
        # The embedded text carries the title (embed_structural_context), the stored text is the body
        assert "Lemon tree" in index.embedder.calls[0][0]

        detail = await index.get_document(document_id)
        assert detail.document is not None and detail.document.title == "Lemon tree"
        assert detail.document.chunk_count == 1 and detail.document.tags == ["eval"]
        assert "Water the lemon tree" in detail.chunks[0]["text"]

        # Unchanged: skipped (None); forced: re-stamped (0); neither embeds again
        assert await index.ingest_file(str(note), params, chunking=KnowledgeChunkingSettings(),
                                       max_file_size_bytes=10_000) is None
        assert await index.ingest_file(str(note), {**params, "force_reingest": True},
                                       chunking=KnowledgeChunkingSettings(), max_file_size_bytes=10_000) == 0
        assert len(index.embedder.calls) == 1

        # Retrieval as the answer graph drives it
        vector = await index.embed_query("lemon")
        hits = await index.vector_search_by_vector(vector, await index.embed_query_sparse("lemon"), top_k=5,
                                                   min_score=0.0)
        assert [h.document_id for h in hits] == [document_id]
        by_id = await index.fetch_hits_by_point_ids([detail.chunks[0]["point_id"], "missing-id"])
        assert [h.document_id for h in by_id] == [document_id]

        assert index.remove_document(document_id) is True
        assert index.remove_document(document_id) is False
        assert (await index.get_document(document_id)).document is None
    finally:
        index.vector_store.close()


@pytest.mark.asyncio
async def test_ingest_file_refuses_a_large_file_and_an_unknown_extension(tmp_path: Path) -> None:
    index = _index(tmp_path)
    try:
        with pytest.raises(ValueError, match="exceeds maximum knowledge ingest size"):
            await index.ingest_file(str(_note(tmp_path)), {}, chunking=KnowledgeChunkingSettings(),
                                    max_file_size_bytes=10)
        other = tmp_path / "x.bin"
        other.write_bytes(b"x")
        with pytest.raises(ValueError, match="Unsupported file extension"):
            await index.ingest_file(str(other), {}, chunking=KnowledgeChunkingSettings(), max_file_size_bytes=10)
    finally:
        index.vector_store.close()


def test_chunking_overlap_must_stay_below_size() -> None:
    with pytest.raises(ValueError):
        KnowledgeChunkingSettings(chunk_size=300, chunk_overlap=300)


class _Graph:
    def __init__(self, answer: str = "", fail: Exception | None = None) -> None:
        self.answer, self.fail, self.seen = answer, fail, None

    async def ainvoke(self, state, config=None):
        self.seen = (dict(state), config)
        if self.fail is not None:
            raise self.fail
        return {"answer": self.answer, "elapsed_ms": 12, "model_id": "m", "effective_leg": "flat",
                "rewritten_query": "q2", "rewrite_keywords": ["k"]}


@pytest.mark.asyncio
async def test_run_answer_writes_its_own_run_row_and_the_result(tmp_path: Path) -> None:
    sink = RecordingLedgerSink(tmp_path)
    graph = _Graph("Tuesdays.")
    state = answer_state("When?", top_k=5, min_score=0.1, rewrite=True, graph_mode="graphiti")
    assert state["graph_temporal"] == "" and state["filters"] == {} and "inbound_id" not in state
    run = await run_answer(graph, sink=sink, query="When?", initial_state=state)
    assert run.run_id and run.run_id.startswith("knowledge-")
    assert graph.seen[1]["configurable"]["run_id"] == run.run_id
    assert run.state["effective_leg"] == "flat"
    result = answer_result("When?", run)
    assert (result.answer, result.run_id, result.rewritten_query, result.keywords) == ("Tuesdays.", run.run_id, "q2", ["k"])
    assert any(r.get("row_kind") == "run" and r.get("status") == "completed" for r in sink.captured)


@pytest.mark.asyncio
async def test_run_answer_nests_under_an_open_run_and_records_a_failure(tmp_path: Path) -> None:
    sink = RecordingLedgerSink(tmp_path)
    parent = RunAccumulator(sink=sink, run_id="chat-1", inbound_id="in-1")
    token = current_run.set(parent)
    try:
        state = answer_state("q", top_k=1, min_score=0.0)
        assert state["inbound_id"] == "in-1"
        run = await run_answer(_Graph("a"), sink=sink, query="q", initial_state=state)
        assert run.run_id == "chat-1"
    finally:
        current_run.reset(token)
    with pytest.raises(RuntimeError):
        await run_answer(_Graph(fail=RuntimeError("boom")), sink=sink, query="q", initial_state=answer_state(
            "q", top_k=1, min_score=0.0))
    assert any(r.get("row_kind") == "run" and r.get("status") == "failed" for r in sink.captured)
