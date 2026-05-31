"""Phase 5b — tests for ``KnowledgeGraphIngestBatchTool`` + the shared
``_run_graph_ingest_for_documents`` helper.

Covers the batch-specific behavior:

* Returns the documented shape ``{document_count, documents[], totals}``.
* Per-document failure isolation — one bad doc doesn't abort the batch;
  totals reflect only what succeeded.
* The ``on_progress`` callback fires once per document (success or failure),
  with the documented payload — that's what 5c will wire to the event bus.
* Input dedup + empty-list short-circuit (no work, no error).
* Single ``KnowledgeGraphIngestTool`` still works (unwraps the batch helper
  cleanly into its single-doc shape — no regression).

Like the resolver/ingest tests, the LLM side is fully stubbed
(``extract_from_chunk`` monkeypatched) so this runs against a real Ladybug
file but no real model.
"""

from __future__ import annotations

import asyncio
import pathlib
from typing import Any

import pytest

ladybug = pytest.importorskip("ladybug")
rapidfuzz = pytest.importorskip("rapidfuzz")

from hirocli.services.knowledge.graph.extractor import (  # noqa: E402
    ExtractionResult,
    ExtractionUsage,
)
from hirocli.services.knowledge.graph.ontology import (  # noqa: E402
    ChunkExtraction,
    ExtractedEntity,
    ExtractedRelation,
)
from hirocli.services.knowledge.models import (  # noqa: E402
    KnowledgeDocumentDetailResult,
    KnowledgeDocumentRow,
)
from hirocli.tools.knowledge_graph import (  # noqa: E402
    KnowledgeGraphIngestBatchTool,
    KnowledgeGraphIngestTool,
    _empty_totals,
    _fold_into_totals,
    _run_graph_ingest_for_documents,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeKnowledgeService:
    """In-memory service stand-in. Returns canned chunks per document_id.

    Use ``set_doc(doc_id, *, title, chunks=[(point_id, text), ...])`` to seed.
    Set ``error_for=doc_id`` to make ``get_document`` raise for one doc
    (exercises per-doc failure isolation)."""

    def __init__(self):
        self._docs: dict[str, dict[str, Any]] = {}
        self.error_for: str | None = None
        self.closed = False

    def set_doc(self, doc_id: str, *, title: str, chunks: list[tuple[str, str]]):
        self._docs[doc_id] = {
            "title": title,
            "chunks": [
                {"point_id": pid, "text": text, "ord": i}
                for i, (pid, text) in enumerate(chunks)
            ],
        }

    async def get_document(
        self, document_id: str, *, chunk_limit: int = 100, chunk_offset: str | None = None
    ):
        if document_id == self.error_for:
            raise RuntimeError(f"simulated failure for {document_id}")
        doc = self._docs.get(document_id)
        if doc is None:
            return KnowledgeDocumentDetailResult(document=None, chunks=[])
        return KnowledgeDocumentDetailResult(
            document=KnowledgeDocumentRow(
                id=document_id,
                source_uri=f"/synthetic/{document_id}.md",
                source_type="file",
                mime="text/markdown",
                ext=".md",
                owner_kind="system",
                owner_id="0",
                category_id=None,
                subcategory_id=None,
                title=doc["title"],
                size_bytes=len("\n".join(c["text"] for c in doc["chunks"])),
                chunk_count=len(doc["chunks"]),
                status="ready",
                error=None,
                ingested_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
                content_hash="x",
                tags=[],
            ),
            chunks=list(doc["chunks"]),
        )

    async def close(self):
        self.closed = True


@pytest.fixture
def fake_workspace(tmp_path, monkeypatch):
    """A bare-bones workspace dir for LadybugDB + the tool's `_resolve_service`.

    Patches ``_resolve_service`` to return our FakeKnowledgeService rather than
    constructing a real KnowledgeService (which would need real Qdrant + embedder).
    Patches LLM resolution + chat model construction so no actual provider is hit.
    Patches ``extract_from_chunk`` so every call returns canned extractions.
    """
    # Patch knowledge service resolver — every tool call lands on the FakeService.
    fake_service = FakeKnowledgeService()
    monkeypatch.setattr(
        "hirocli.tools.knowledge_graph._resolve_service",
        lambda runtime, workspace: (fake_service, tmp_path, False),
    )

    # Patch model resolution: pretend extraction model is configured (any non-None
    # ResolvedModel works — the model object never reaches the LLM because
    # extract_from_chunk is stubbed below).
    class _ResolvedStub:
        model_id = "stub:stub"
        temperature = 0.0
        max_tokens = 1024
        thinking = "off"

    monkeypatch.setattr(
        "hirocli.tools.knowledge_graph.resolve_knowledge_graph_extraction_llm",
        lambda prefs, workspace_path: _ResolvedStub(),
    )
    # Disambig optional — return None so disambiguator stays unset (simpler).
    monkeypatch.setattr(
        "hirocli.tools.knowledge_graph.resolve_knowledge_graph_disambiguation_llm",
        lambda prefs, workspace_path: None,
    )
    monkeypatch.setattr(
        "hirocli.tools.knowledge_graph.create_chat_model",
        lambda model_id, **kw: object(),  # placeholder; extractor is stubbed
    )
    monkeypatch.setattr(
        "hirocli.tools.knowledge_graph.load_preferences",
        lambda workspace_path: object(),
    )

    # Patch the extractor to return canned results regardless of input.
    async def fake_extract(text, *, model):
        # Tiny extraction proportional to the chunk's content so different
        # documents produce different entity counts (useful for totals).
        first_word = (text or "").strip().split()[:1]
        ent_name = (first_word[0] if first_word else "Entity").strip(".,!?").capitalize()[:30] or "Entity"
        return ExtractionResult(
            extraction=ChunkExtraction(
                entities=[ExtractedEntity(name=ent_name, type="Person")],
                relations=[],
            ),
            usage=ExtractionUsage(input_tokens=50, output_tokens=20),
        )

    monkeypatch.setattr(
        "hirocli.services.knowledge.graph.ingest.extract_from_chunk", fake_extract
    )
    return fake_service, tmp_path


# ---------------------------------------------------------------------------
# Helper unit tests — totals math
# ---------------------------------------------------------------------------


def test_empty_totals_has_all_expected_keys() -> None:
    t = _empty_totals()
    for k in (
        "entities_created", "entities_linked_exact", "edges_written",
        "llm_extraction_calls", "total_input_tokens", "chunks_processed",
    ):
        assert k in t and t[k] == 0


def test_fold_into_totals_sums_int_fields_and_ignores_strings() -> None:
    t = _empty_totals()
    _fold_into_totals(t, {"entities_created": 3, "edges_written": 2, "garbage": "x"})
    _fold_into_totals(t, {"entities_created": 5, "edges_written": 1})
    assert t["entities_created"] == 8
    assert t["edges_written"] == 3
    # Unknown keys in stats are ignored (we never touch them on totals).
    assert "garbage" not in t


# ---------------------------------------------------------------------------
# Batch tool — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_tool_returns_documented_shape(fake_workspace) -> None:
    fake, _ = fake_workspace
    fake.set_doc("d1", title="trips.md", chunks=[("c1", "Paris was great.")])
    fake.set_doc("d2", title="family.md", chunks=[("c2", "Sara called today.")])

    tool = KnowledgeGraphIngestBatchTool()
    result = await tool.execute_async(document_ids=["d1", "d2"])

    assert result["document_count"] == 2
    assert {d["document_id"] for d in result["documents"]} == {"d1", "d2"}
    assert all(d["ok"] for d in result["documents"])
    # Totals fold per-doc stats — non-zero entity creations across the two docs.
    assert result["totals"]["entities_created"] >= 2
    assert result["totals"]["llm_extraction_calls"] >= 2


@pytest.mark.asyncio
async def test_batch_tool_dedupes_repeated_ids(fake_workspace) -> None:
    fake, _ = fake_workspace
    fake.set_doc("d1", title="t.md", chunks=[("c1", "Hello.")])

    tool = KnowledgeGraphIngestBatchTool()
    result = await tool.execute_async(document_ids=["d1", "d1", "  ", "d1"])
    # Three ids collapse to one (deduped + whitespace filtered).
    assert result["document_count"] == 1
    assert len(result["documents"]) == 1


@pytest.mark.asyncio
async def test_batch_tool_empty_list_short_circuits(fake_workspace) -> None:
    tool = KnowledgeGraphIngestBatchTool()
    result = await tool.execute_async(document_ids=[])
    assert result["document_count"] == 0
    assert result["documents"] == []
    assert result["totals"] == _empty_totals()


@pytest.mark.asyncio
async def test_batch_tool_rejects_non_list_input(fake_workspace) -> None:
    tool = KnowledgeGraphIngestBatchTool()
    with pytest.raises(ValueError, match="must be a list"):
        await tool.execute_async(document_ids="d1")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Per-doc failure isolation — one bad doc, others succeed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_continues_when_one_document_fails(fake_workspace) -> None:
    fake, _ = fake_workspace
    fake.set_doc("good_1", title="ok.md", chunks=[("c1", "Maya.")])
    fake.set_doc("good_2", title="also_ok.md", chunks=[("c2", "Selim.")])
    fake.error_for = "bad"  # get_document raises for this id

    tool = KnowledgeGraphIngestBatchTool()
    result = await tool.execute_async(
        document_ids=["good_1", "bad", "good_2"]
    )

    assert result["document_count"] == 3
    by_id = {d["document_id"]: d for d in result["documents"]}
    assert by_id["good_1"]["ok"] is True
    assert by_id["good_2"]["ok"] is True
    assert by_id["bad"]["ok"] is False
    assert "simulated failure" in by_id["bad"]["error"]
    # Totals only count the successful docs (≥ 2 entity creations).
    assert result["totals"]["entities_created"] >= 2


# ---------------------------------------------------------------------------
# on_progress callback — what 5c will hook into for streaming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_helper_on_progress_fires_once_per_document_with_payload(
    fake_workspace,
) -> None:
    fake, workspace_path = fake_workspace
    fake.set_doc("a", title="a.md", chunks=[("c1", "Alpha.")])
    fake.set_doc("b", title="b.md", chunks=[("c2", "Beta.")])
    fake.error_for = "b"  # the second doc will fail

    events: list[dict] = []
    result = await _run_graph_ingest_for_documents(
        fake,
        workspace_path,
        ["a", "b"],
        source_role="user_document",
        on_progress=events.append,
    )

    assert len(events) == 2
    # Each event carries the documented fields.
    for ev in events:
        for k in ("index", "total", "document_id", "document_title", "ok", "stats", "error"):
            assert k in ev
        assert ev["total"] == 2
    # Order matches the input list (index 0 then index 1).
    assert events[0]["document_id"] == "a" and events[0]["index"] == 0
    assert events[1]["document_id"] == "b" and events[1]["index"] == 1
    # Failure event marks ok=False and includes the error message.
    assert events[1]["ok"] is False
    assert "simulated failure" in events[1]["error"]
    # The returned result mirrors what the events showed (consistency check).
    assert result["documents"][1]["error"] == events[1]["error"]


@pytest.mark.asyncio
async def test_helper_progress_callback_exception_does_not_abort_batch(
    fake_workspace,
) -> None:
    """If 5c's event-bus emitter raises, batch processing must continue.
    A logging glitch shouldn't lose graph mutations the rest of the batch made."""
    fake, workspace_path = fake_workspace
    fake.set_doc("a", title="a.md", chunks=[("c1", "Alpha.")])
    fake.set_doc("b", title="b.md", chunks=[("c2", "Beta.")])

    def boom(_payload):
        raise RuntimeError("simulated event-bus failure")

    result = await _run_graph_ingest_for_documents(
        fake, workspace_path, ["a", "b"],
        source_role="user_document", on_progress=boom,
    )
    # Both docs still succeeded — callback errors are swallowed (logged).
    assert all(d["ok"] for d in result["documents"])
    assert result["totals"]["entities_created"] >= 2


# ---------------------------------------------------------------------------
# Single-doc tool — still works after the refactor (no regression)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_doc_tool_unwraps_batch_into_doc_shape(fake_workspace) -> None:
    fake, _ = fake_workspace
    fake.set_doc("only", title="only.md", chunks=[("c1", "Hello.")])

    tool = KnowledgeGraphIngestTool()
    result = await tool.execute_async(document_id="only")
    # Single-doc shape (the public API this tool has always returned).
    assert result["document_id"] == "only"
    assert result["document_title"] == "only.md"
    assert result["ok"] is True
    assert isinstance(result["stats"], dict)
    assert result["stats"]["entities_created"] >= 1


@pytest.mark.asyncio
async def test_single_doc_tool_surfaces_failure_inline(fake_workspace) -> None:
    fake, _ = fake_workspace
    fake.error_for = "broken"
    tool = KnowledgeGraphIngestTool()
    result = await tool.execute_async(document_id="broken")
    assert result["document_id"] == "broken"
    assert result["ok"] is False
    assert "simulated failure" in result["error"]
