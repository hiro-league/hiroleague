"""``graph_build``: a collection's documents become one episode per chunk (uuid = point id) in the service's group, a
bad document doesn't stop the batch, the keyword index is rebuilt once; and a document's episodes are removed."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from hiro_memory.knowledge.graph_build import build_document_graph, empty_graph_totals, remove_document_episodes
from hiro_memory.knowledge.models import KnowledgeDocumentDetailResult


def _doc(document_id: str, title: str) -> Any:
    return SimpleNamespace(id=document_id, title=title)


class _Index:
    """``get_document`` over two pages for doc-a, one for doc-b, none for doc-x."""

    async def get_document(self, document_id: str, *, chunk_limit: int = 100, chunk_offset: str | None = None):
        if document_id == "doc-a":
            if chunk_offset is None:
                return KnowledgeDocumentDetailResult(document=_doc("doc-a", "A"), chunks=[
                    {"point_id": "p1", "text": "first"}, {"point_id": "", "text": "no id"}], chunk_next_offset="2")
            return KnowledgeDocumentDetailResult(document=_doc("doc-a", "A"), chunks=[
                {"point_id": "p2", "text": "second"}, {"point_id": "p3", "text": "  "}])
        if document_id == "doc-b":
            return KnowledgeDocumentDetailResult(document=_doc("doc-b", "B"), chunks=[{"point_id": "p4", "text": "b"}])
        return KnowledgeDocumentDetailResult(document=None, chunks=[])


class _Service:
    def __init__(self) -> None:
        self.initialized = 0
        self.ingested: list[tuple[list[str], dict[str, Any]]] = []
        self.rebuilt = 0
        self.removed: list[str] = []

    async def initialize(self) -> None:
        self.initialized += 1

    async def ingest_chunks(self, episodes, **kwargs):
        self.ingested.append(([e.chunk_id for e in episodes], kwargs))
        return SimpleNamespace(as_dict=lambda: {"episodes_processed": len(episodes), "entities_total": 2})

    async def rebuild_search_index(self) -> None:
        self.rebuilt += 1

    async def remove_episodes_by_document(self, document_id: str) -> int:
        self.removed.append(document_id)
        return 3


@pytest.mark.asyncio
async def test_build_document_graph_one_episode_per_chunk_and_isolated_failures() -> None:
    service = _Service()
    progress: list[dict[str, Any]] = []
    out = await build_document_graph(service, _Index(), ["doc-a", "doc-x", "doc-b"], source_role="user_document",
                                     on_progress=progress.append)
    assert service.initialized == 1 and service.rebuilt == 1
    assert [ids for ids, _ in service.ingested] == [["p1", "p2"], ["p4"]]
    assert all(kw["rebuild_fts"] is False and kw["source_role"] == "user_document" for _, kw in service.ingested)
    assert [d["ok"] for d in out["documents"]] == [True, False, True]
    assert "KeyError" in out["documents"][1]["error"]
    assert out["documents"][0]["document_title"] == "A"
    assert out["totals"]["episodes_processed"] == 3 and out["totals"]["entities_total"] == 4
    assert [p["document_id"] for p in progress] == ["doc-a", "doc-x", "doc-b"]


@pytest.mark.asyncio
async def test_build_document_graph_with_no_documents_touches_nothing() -> None:
    service = _Service()
    out = await build_document_graph(service, _Index(), [], source_role="user_document")
    assert out == {"document_count": 0, "documents": [], "totals": empty_graph_totals()}
    assert service.initialized == 0


@pytest.mark.asyncio
async def test_remove_document_episodes() -> None:
    service = _Service()
    assert await remove_document_episodes(service, "  ") == 0
    assert await remove_document_episodes(service, " doc-a ") == 3
    assert service.removed == ["doc-a"]
