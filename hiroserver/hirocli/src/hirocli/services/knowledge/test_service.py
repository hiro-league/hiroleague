from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.services.knowledge.service import KnowledgeService


class FakeEmbedder:
    dimension = 8

    def embed_texts(self, texts):
        vectors = []
        for text in texts:
            values = [0.0] * self.dimension
            for index, byte in enumerate(text.encode("utf-8")):
                values[index % self.dimension] += (byte % 31) / 31
            norm = sum(value * value for value in values) ** 0.5 or 1
            vectors.append([value / norm for value in values])
        return vectors


@pytest.mark.asyncio
async def test_markdown_ingest_search_and_detail(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    docs = tmp_path / "docs"
    docs.mkdir()
    note = docs / "note.md"
    note.write_text(
        "# Alpha\n\nHiro knowledge stores markdown chunks.\n\n"
        "## Search\n\nVector search finds evidence.",
        encoding="utf-8",
    )

    service = KnowledgeService(workspace, embedder=FakeEmbedder())
    try:
        scan = await service.scan_folder(str(docs))
        assert len(scan.files) == 1
        assert scan.files[0].supported is True

        job = await service.ingest_and_wait([str(note)], tags=["smoke"])
        assert job.status == "completed"
        assert job.totals["ingested"] == 1
        assert job.totals["chunks"] == 2

        documents = await service.list_documents()
        assert documents.total == 1
        assert documents.documents[0].title == "Alpha"

        search = await service.search("markdown evidence", top_k=3)
        assert search.hits
        assert search.hits[0].title == "Alpha"

        detail = await service.get_document(documents.documents[0].id)
        assert detail.document is not None
        assert len(detail.chunks) == 2
        assert detail.chunks[0]["heading_path"] == "# Alpha"
    finally:
        await service.close()
