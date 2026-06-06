from __future__ import annotations

from pathlib import Path
import json
import sqlite3
import asyncio

import pytest
from langchain_core.messages import AIMessage

from hirocli.domain.preferences import WorkspacePreferences, save_preferences
import hirocli.services.knowledge.agent.graph as knowledge_graph_module
from hirocli.services.knowledge.agent.graph import KnowledgeAgentGraph
from hirocli.services.knowledge.agent.helpers import NormalizedQuery, QueryRewrite
from hirocli.services.knowledge import service as knowledge_service_module
from hirocli.services.knowledge.live_registry import maybe_recover_abandoned_work
from hirocli.services.knowledge.runtime_owner import current_owner_token
from hirocli.services.knowledge.constants import DEFAULT_FILE_CONCURRENCY
from hirocli.services.knowledge.service import KnowledgeService
from hirocli.runtime.preferences_runtime import PreferencePathError, WorkspacePreferencesRuntime


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


class FakeSparseEmbedder:
    """Avoids a real BM25 weight download during tests; deterministic sparse vectors."""

    model_name = "fake-bm25"

    def embed_documents(self, texts):
        return [([0, (len(text) % 7) + 1], [1.0, 1.0]) for text in texts]

    def embed_query(self, text):
        return ([0], [1.0])


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

    service = KnowledgeService(workspace, embedder=FakeEmbedder(), sparse_embedder=FakeSparseEmbedder())
    try:
        scan = await service.scan_folder(str(docs))
        assert len(scan.files) == 1
        assert scan.files[0].supported is True

        job = await service.ingest_and_wait([str(note)], tags=["smoke"])
        assert job.status == "completed"
        assert job.totals["ingested"] == 1
        assert job.totals["chunks"] == 2

        jobs = await service.list_jobs()
        assert len(jobs.jobs) == 1
        assert jobs.jobs[0].status == "completed"
        assert jobs.jobs[0].totals["chunks"] == 2

        category = await service.create_category("Docs")
        subcategory = await service.create_category("Design", parent_id=category["id"])
        tag = await service.create_tag("phase1")
        assert category["parent_id"] is None
        assert subcategory["parent_id"] == category["id"]
        assert tag["name"] == "phase1"

        documents = await service.list_documents()
        assert documents.total == 1
        assert documents.documents[0].title == "Alpha"

        search = await service.search("markdown evidence", top_k=3)
        assert search.hits
        assert search.hits[0].title == "Alpha"

        detail = await service.get_document(documents.documents[0].id)
        assert detail.document is not None
        assert detail.document.tags == ["smoke"]
        assert len(detail.chunks) == 2
        assert detail.chunks[0]["heading_path"] == "# Alpha"

        updated = await service.update_document_metadata(
            documents.documents[0].id,
            owner_kind="character",
            owner_id="hiro",
            category_id=category["id"],
            subcategory_id=subcategory["id"],
            tags=["phase1", "updated"],
        )
        assert updated.owner_kind == "character"
        filtered = await service.search("evidence", filters={"owner_kind": "character", "tags": ["updated"]})
        assert filtered.hits

        answer = await service.answer("What stores markdown chunks?", top_k=2)
        assert answer.sources
        assert "[1]" in answer.answer

        runtime = WorkspacePreferencesRuntime(workspace)
        with pytest.raises(PreferencePathError):
            runtime.update("knowledge.default_embedding_model", "openai:text-embedding-3-small")

        deleted = await service.delete_document(documents.documents[0].id)
        assert deleted["deleted"] is True
        assert (await service.list_documents()).total == 0
    finally:
        await service.close()


async def _ingest_one_document(service: KnowledgeService, tmp_path: Path) -> str:
    """Ingest a single markdown note and return its document id."""
    docs = tmp_path / "docs"
    docs.mkdir()
    note = docs / "note.md"
    note.write_text("# Alpha\n\nHiro knowledge stores markdown chunks.", encoding="utf-8")
    job = await service.ingest_and_wait([str(note)])
    assert job.status == "completed"
    documents = await service.list_documents()
    return documents.documents[0].id


@pytest.mark.asyncio
async def test_delete_document_purges_graph_episodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deleting a document must also purge its Graphiti episodes (orphan-cleanup gap)."""
    import hirocli.tools.knowledge_graph as knowledge_graph_tool

    workspace = tmp_path / "workspace"
    service = KnowledgeService(workspace, embedder=FakeEmbedder(), sparse_embedder=FakeSparseEmbedder())
    calls: list[tuple[Path, str]] = []

    async def fake_remove(workspace_path: Path, document_id: str) -> int:
        calls.append((workspace_path, document_id))
        return 3

    monkeypatch.setattr(knowledge_graph_tool, "remove_document_from_graph", fake_remove)
    try:
        document_id = await _ingest_one_document(service, tmp_path)
        deleted = await service.delete_document(document_id)
        assert deleted["deleted"] is True
        assert calls == [(service.workspace_path, document_id)]
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_delete_document_graph_failure_does_not_block_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A graph teardown failure must not roll back the committed catalog/Qdrant delete."""
    import hirocli.tools.knowledge_graph as knowledge_graph_tool

    workspace = tmp_path / "workspace"
    service = KnowledgeService(workspace, embedder=FakeEmbedder(), sparse_embedder=FakeSparseEmbedder())

    async def boom(workspace_path: Path, document_id: str) -> int:
        raise RuntimeError("graph DB busy")

    monkeypatch.setattr(knowledge_graph_tool, "remove_document_from_graph", boom)
    try:
        document_id = await _ingest_one_document(service, tmp_path)
        deleted = await service.delete_document(document_id)
        # The Qdrant/catalog delete is still reported as successful despite the graph error.
        assert deleted["deleted"] is True
        assert (await service.list_documents()).total == 0
    finally:
        await service.close()


def test_knowledge_crash_recovery_marks_running_jobs_failed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    service = KnowledgeService(workspace, embedder=FakeEmbedder(), sparse_embedder=FakeSparseEmbedder())
    db_path = service.db_path
    try:
        with sqlite3.connect(db_path) as con:
            con.execute(
                """
                INSERT INTO knowledge_ingestion_jobs
                (id, created_at, finished_at, status, totals_json, errors_json, params_json)
                VALUES ('job-1', '2026-01-01T00:00:00+00:00', NULL, 'running', ?, '{}', '{}')
                """,
                (json.dumps({"requested": 1}),),
            )
    finally:
        import asyncio

        asyncio.run(service.close())

    maybe_recover_abandoned_work(workspace)
    recovered = KnowledgeService(workspace, embedder=FakeEmbedder(), sparse_embedder=FakeSparseEmbedder())
    try:
        with sqlite3.connect(db_path) as con:
            row = con.execute("SELECT status, errors_json FROM knowledge_ingestion_jobs WHERE id = 'job-1'").fetchone()
        assert row[0] == "failed"
        assert json.loads(row[1])["job"] == "server restarted"
    finally:
        import asyncio

        asyncio.run(recovered.close())


def test_knowledge_crash_recovery_only_fails_documents_from_abandoned_jobs(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    abandoned_path = str((tmp_path / "abandoned.md").resolve())
    unrelated_path = str((tmp_path / "unrelated.md").resolve())
    service = KnowledgeService(workspace, embedder=FakeEmbedder(), sparse_embedder=FakeSparseEmbedder())
    db_path = service.db_path
    try:
        with sqlite3.connect(db_path) as con:
            con.executemany(
                """
                INSERT INTO knowledge_documents
                (id, source_uri, source_type, mime, ext, owner_kind, owner_id, title, size_bytes, status, updated_at)
                VALUES (?, ?, 'file', 'text/markdown', '.md', 'system', '0', ?, 12, 'embedding', '2026-01-01T00:00:00+00:00')
                """,
                [
                    ("doc-abandoned", abandoned_path, "abandoned.md"),
                    ("doc-unrelated", unrelated_path, "unrelated.md"),
                ],
            )
            con.execute(
                """
                INSERT INTO knowledge_ingestion_jobs
                (id, created_at, finished_at, status, totals_json, errors_json, params_json)
                VALUES ('job-1', '2026-01-01T00:00:00+00:00', NULL, 'running', ?, '{}', ?)
                """,
                (
                    json.dumps({"requested": 1}),
                    json.dumps({"paths": [abandoned_path]}),
                ),
            )
    finally:
        import asyncio

        asyncio.run(service.close())

    maybe_recover_abandoned_work(workspace)
    recovered = KnowledgeService(workspace, embedder=FakeEmbedder(), sparse_embedder=FakeSparseEmbedder())
    try:
        with sqlite3.connect(db_path) as con:
            rows = {
                row[0]: row[1]
                for row in con.execute(
                    "SELECT id, status FROM knowledge_documents ORDER BY id"
                ).fetchall()
            }
        assert rows["doc-abandoned"] == "failed"
        assert rows["doc-unrelated"] == "embedding"
    finally:
        import asyncio

        asyncio.run(recovered.close())


def test_maybe_recover_skips_when_live_service_registered(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    service = KnowledgeService(workspace, embedder=FakeEmbedder(), sparse_embedder=FakeSparseEmbedder())
    db_path = service.db_path
    try:
        with sqlite3.connect(db_path) as con:
            con.execute(
                """
                INSERT INTO knowledge_ingestion_jobs
                (id, created_at, finished_at, status, totals_json, errors_json, params_json, owner_token)
                VALUES ('job-live', '2026-01-01T00:00:00+00:00', NULL, 'running', ?, '{}', '{}', ?)
                """,
                (json.dumps({"requested": 1}), service.owner_token),
            )
        maybe_recover_abandoned_work(workspace)
        with sqlite3.connect(db_path) as con:
            row = con.execute(
                "SELECT status FROM knowledge_ingestion_jobs WHERE id = 'job-live'"
            ).fetchone()
        assert row[0] == "running"
    finally:
        import asyncio

        asyncio.run(service.close())


def test_recovery_only_fails_jobs_with_dead_owner_token(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    service = KnowledgeService(workspace, embedder=FakeEmbedder(), sparse_embedder=FakeSparseEmbedder())
    db_path = service.db_path
    dead_token = f"{current_owner_token().split(':', 1)[0]}:999999:deadbeef"
    live_token = current_owner_token()
    try:
        with sqlite3.connect(db_path) as con:
            con.executescript(
                f"""
                INSERT INTO knowledge_ingestion_jobs
                (id, created_at, finished_at, status, totals_json, errors_json, params_json, owner_token)
                VALUES
                  ('job-dead', '2026-01-01T00:00:00+00:00', NULL, 'running', '{{"requested": 1}}', '{{}}', '{{}}', '{dead_token}'),
                  ('job-live', '2026-01-01T00:00:00+00:00', NULL, 'running', '{{"requested": 1}}', '{{}}', '{{}}', '{live_token}');
                """
            )
    finally:
        import asyncio

        asyncio.run(service.close())

    maybe_recover_abandoned_work(workspace)
    with sqlite3.connect(db_path) as con:
        rows = {
            row[0]: row[1]
            for row in con.execute("SELECT id, status FROM knowledge_ingestion_jobs ORDER BY id").fetchall()
        }
    assert rows["job-dead"] == "failed"
    assert rows["job-live"] == "running"


@pytest.mark.asyncio
async def test_direct_save_preferences_enforces_knowledge_embedding_lock(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    docs = tmp_path / "docs"
    docs.mkdir()
    note = docs / "note.md"
    note.write_text("# Alpha\n\nIndexed text.", encoding="utf-8")

    service = KnowledgeService(workspace, embedder=FakeEmbedder(), sparse_embedder=FakeSparseEmbedder())
    try:
        await service.ingest_and_wait([str(note)])
        prefs = WorkspacePreferences()
        prefs.knowledge.default_embedding_model = "openai:text-embedding-3-small"
        with pytest.raises(ValueError):
            save_preferences(workspace, prefs, previous=WorkspacePreferences())
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_ingest_job_processes_files_with_bounded_parallelism(tmp_path: Path) -> None:
    class SlowKnowledgeService(KnowledgeService):
        def __init__(self, workspace_path: Path) -> None:
            super().__init__(workspace_path, embedder=FakeEmbedder(), sparse_embedder=FakeSparseEmbedder())
            self.current = 0
            self.max_seen = 0

        async def _ingest_one(self, raw_path: str, params: dict, **kwargs) -> int | None:
            self.current += 1
            self.max_seen = max(self.max_seen, self.current)
            await asyncio.sleep(0.05)
            self.current -= 1
            return 1

    service = SlowKnowledgeService(tmp_path / "workspace")
    try:
        job_id = "job-parallel"
        paths = [str(tmp_path / f"{index}.md") for index in range(DEFAULT_FILE_CONCURRENCY + 2)]
        await asyncio.to_thread(
            service._insert_job,
            job_id,
            "running",
            {"requested": len(paths), "skipped": 0, "ingested": 0, "failed": 0, "chunks": 0},
            {},
            {},
        )
        await service._run_ingest_job(job_id, paths, {"file_concurrency": 4})
        job = await service.job_status(job_id)
        assert job.status == "completed"
        assert job.totals["ingested"] == len(paths)
        assert 1 < service.max_seen <= DEFAULT_FILE_CONCURRENCY
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_max_file_size_guardrail_fails_before_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    note = tmp_path / "large.md"
    note.write_text("# Large\n\nThis file is too large for the patched test limit.", encoding="utf-8")
    monkeypatch.setattr(knowledge_service_module, "MAX_FILE_SIZE_BYTES", 10)

    service = KnowledgeService(workspace, embedder=FakeEmbedder(), sparse_embedder=FakeSparseEmbedder())
    try:
        job = await service.ingest_and_wait([str(note)])
        assert job.status == "failed"
        assert "exceeds maximum knowledge ingest size" in job.errors[str(note.resolve())]
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_category_subcategory_assignment_must_match(tmp_path: Path) -> None:
    service = KnowledgeService(tmp_path / "workspace", embedder=FakeEmbedder(), sparse_embedder=FakeSparseEmbedder())
    try:
        category_a = await service.create_category("A")
        category_b = await service.create_category("B")
        sub_b = await service.create_category("B child", parent_id=category_b["id"])

        with pytest.raises(ValueError, match="must belong"):
            await service.start_ingest(
                [str(tmp_path / "note.md")],
                category_id=category_a["id"],
                subcategory_id=sub_b["id"],
            )
        with pytest.raises(ValueError, match="requires category_id"):
            await service.start_ingest([str(tmp_path / "note.md")], subcategory_id=sub_b["id"])
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_update_document_metadata_rejects_mismatched_subcategory(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    note = tmp_path / "note.md"
    note.write_text("# Alpha\n\nIndexed text.", encoding="utf-8")
    service = KnowledgeService(workspace, embedder=FakeEmbedder(), sparse_embedder=FakeSparseEmbedder())
    try:
        await service.ingest_and_wait([str(note)])
        documents = await service.list_documents()
        category_a = await service.create_category("A")
        category_b = await service.create_category("B")
        sub_b = await service.create_category("B child", parent_id=category_b["id"])

        with pytest.raises(ValueError, match="must belong"):
            await service.update_document_metadata(
                documents.documents[0].id,
                owner_kind="system",
                owner_id="0",
                category_id=category_a["id"],
                subcategory_id=sub_b["id"],
            )
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_update_document_metadata_keeps_payload_flat(tmp_path: Path) -> None:
    """Metadata updates must not write a nested ``metadata`` snapshot."""
    workspace = tmp_path / "workspace"
    note = tmp_path / "note.md"
    note.write_text("# Alpha\n\nIndexed text.", encoding="utf-8")
    service = KnowledgeService(workspace, embedder=FakeEmbedder(), sparse_embedder=FakeSparseEmbedder())
    try:
        await service.ingest_and_wait([str(note)])
        documents = await service.list_documents()
        document_id = documents.documents[0].id
        category = await service.create_category("Docs")
        subcategory = await service.create_category("Design", parent_id=category["id"])

        await service.update_document_metadata(
            document_id,
            owner_kind="system",
            owner_id="0",
            category_id=category["id"],
            subcategory_id=subcategory["id"],
            tags=["first"],
        )
        await service.update_document_metadata(
            document_id,
            owner_kind="system",
            owner_id="0",
            category_id=category["id"],
            subcategory_id=subcategory["id"],
            tags=["second"],
        )

        detail = await service.get_document(document_id)
        assert detail.chunks
        for chunk in detail.chunks:
            assert "metadata" not in chunk
            assert chunk.get("tags") == ["second"]
            assert chunk.get("category_id") == category["id"]
            assert chunk.get("subcategory_id") == subcategory["id"]
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_reingest_unchanged_content_updates_ingested_at(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    note = tmp_path / "note.md"
    note.write_text("# Alpha\n\nIndexed text.", encoding="utf-8")
    service = KnowledgeService(workspace, embedder=FakeEmbedder(), sparse_embedder=FakeSparseEmbedder())
    try:
        await service.ingest_and_wait([str(note)])
        document_id = (await service.list_documents()).documents[0].id
        before = (await service.get_document(document_id)).document
        assert before is not None
        assert before.ingested_at is not None

        await asyncio.sleep(1.1)
        job = await service.reingest_document(document_id)
        task = service._tasks.get(job.job_id)
        assert task is not None
        await task

        after = (await service.get_document(document_id)).document
        assert after is not None
        assert after.ingested_at is not None
        assert after.ingested_at > before.ingested_at
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_metadata_update_bumps_updated_at_not_ingested_at(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    note = tmp_path / "note.md"
    note.write_text("# Alpha\n\nIndexed text.", encoding="utf-8")
    service = KnowledgeService(workspace, embedder=FakeEmbedder(), sparse_embedder=FakeSparseEmbedder())
    try:
        await service.ingest_and_wait([str(note)])
        document_id = (await service.list_documents()).documents[0].id
        before = (await service.get_document(document_id)).document
        assert before is not None
        assert before.ingested_at is not None

        await asyncio.sleep(1.1)
        await service.update_document_metadata(
            document_id,
            owner_kind="system",
            owner_id="0",
            tags=["edited"],
        )

        after = (await service.get_document(document_id)).document
        assert after is not None
        assert after.tags == ["edited"]
        assert after.ingested_at == before.ingested_at
        assert after.updated_at > before.updated_at
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_reingest_document_returns_running_job_without_blocking(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    note = tmp_path / "note.md"
    note.write_text("# Alpha\n\nIndexed text.", encoding="utf-8")

    class SlowKnowledgeService(KnowledgeService):
        async def _ingest_one(self, raw_path: str, params: dict, **kwargs) -> int | None:
            await asyncio.sleep(0.15)
            return await super()._ingest_one(raw_path, params, **kwargs)

    service = SlowKnowledgeService(workspace)
    try:
        await service.ingest_and_wait([str(note)])
        document_id = (await service.list_documents()).documents[0].id

        started = await service.reingest_document(document_id)
        assert started.status == "running"
        assert started.job_id

        task = service._tasks.get(started.job_id)
        assert task is not None
        await task
        finished = await service.job_status(started.job_id)
        assert finished.status == "completed"
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_answer_skips_call_model_when_no_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm_called: list[bool] = []

    class FakeEmbedService:
        async def embed_query(self, query: str) -> list[float]:
            return [0.1] * 8

        async def embed_query_sparse(self, query: str):
            return ([0], [1.0])

        async def vector_search_by_vector(self, vector, sparse_vector=None, **kwargs) -> list:
            return []

    def fail_create_chat_model(*_args, **_kwargs):
        llm_called.append(True)
        raise AssertionError("call_model should not run when retrieval returns no hits")

    monkeypatch.setattr(knowledge_graph_module, "create_chat_model", fail_create_chat_model)
    prefs = WorkspacePreferences()
    graph = KnowledgeAgentGraph(
        workspace_path=tmp_path / "workspace",
        service=FakeEmbedService(),
        prefs=prefs,
    ).build()
    state = await graph.ainvoke(
        {
            "query": "anything",
            "filters": {},
            "top_k": 5,
            "min_score": 0.9,
        }
    )
    assert llm_called == []
    assert state.get("no_results") is True
    assert state.get("answer") in (None, "")
    assert state.get("sources") == []


@pytest.mark.asyncio
async def test_answer_prompt_honors_citation_and_language_preferences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    class FakeModel:
        async def ainvoke(self, messages):
            captured["system"] = messages[0].content
            return AIMessage(content="answer")

    def fake_create_chat_model(*args, **kwargs):
        return FakeModel()

    from hirocli.domain.preferences import ResolvedModel

    monkeypatch.setattr(knowledge_graph_module, "create_chat_model", fake_create_chat_model)
    monkeypatch.setattr(
        knowledge_graph_module,
        "resolve_knowledge_answering_llm",
        lambda *_args, **_kwargs: ResolvedModel(
            model_id="fake:model",
            temperature=0.2,
            max_tokens=1600,
        ),
    )
    prefs = WorkspacePreferences()
    prefs.knowledge.answering.cite_sources = False
    prefs.knowledge.answering.language_policy = "prefer_arabic"
    graph = KnowledgeAgentGraph(
        workspace_path=tmp_path / "workspace",
        service=object(),
        prefs=prefs,
    )
    state = {
        "normalized_query": NormalizedQuery(raw="hello", text="hello", language="en"),
        "context": "[1] Source\nText",
        "sources": [object()],
    }

    result = await graph.call_model(state)

    assert result["answer"] == "answer"
    assert "Do not include footnote references" in captured["system"]
    assert "Cite evidence" not in captured["system"]
    assert "Answer in Arabic" in captured["system"]


def _rewrite_graph(tmp_path: Path, prefs: WorkspacePreferences | None = None) -> KnowledgeAgentGraph:
    return KnowledgeAgentGraph(
        workspace_path=tmp_path / "workspace",
        service=object(),
        prefs=prefs or WorkspacePreferences(),
    )


class _FakeSpec:
    def __init__(self, features: list[str]) -> None:
        self.features = features


class _FakeCatalog:
    def __init__(self, features: list[str]) -> None:
        self._features = features

    def get_model(self, _model_id: str) -> _FakeSpec:
        return _FakeSpec(self._features)


def _patch_rewrite_llm(monkeypatch: pytest.MonkeyPatch, *, structured_output: bool = True) -> None:
    """Patch the rewrite resolver + catalog so the node reaches the model call in tests.

    Tuning (temperature / max_tokens / thinking) comes from the knowledge_rewrite profile via
    ResolvedModel — never hardcoded in the node.
    """
    from hirocli.domain.preferences import ResolvedModel

    monkeypatch.setattr(
        knowledge_graph_module,
        "resolve_knowledge_rewrite_llm",
        lambda *_a, **_k: ResolvedModel(
            model_id="google:gemini-3-flash-preview",
            temperature=0.0,
            max_tokens=1024,
            thinking="off",
        ),
    )
    monkeypatch.setattr(
        knowledge_graph_module,
        "get_model_catalog",
        lambda: _FakeCatalog(["structured_output"] if structured_output else []),
    )


@pytest.mark.asyncio
async def test_rewrite_query_noop_when_disabled(tmp_path: Path) -> None:
    graph = _rewrite_graph(tmp_path)
    state = {
        "rewrite": False,
        "normalized_query": NormalizedQuery(raw="hi", text="hi", language="en"),
    }
    assert await graph.rewrite_query(state) == {}


@pytest.mark.asyncio
async def test_rewrite_query_skips_empty_query(tmp_path: Path) -> None:
    graph = _rewrite_graph(tmp_path)
    state = {
        "rewrite": True,
        "normalized_query": NormalizedQuery(raw="   ", text="   ", language="unknown"),
    }
    # Nothing to rewrite — skip before resolving or calling any model.
    assert await graph.rewrite_query(state) == {}


@pytest.mark.asyncio
async def test_rewrite_query_skips_when_no_llm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        knowledge_graph_module, "resolve_knowledge_rewrite_llm", lambda *_a, **_k: None
    )
    graph = _rewrite_graph(tmp_path)
    state = {
        "rewrite": True,
        "normalized_query": NormalizedQuery(raw="hi", text="hi", language="en"),
    }
    # No model configured → silent passthrough, retrieval proceeds on the normalized query.
    assert await graph.rewrite_query(state) == {}


@pytest.mark.asyncio
async def test_rewrite_query_skips_when_model_lacks_structured_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[bool] = []
    _patch_rewrite_llm(monkeypatch, structured_output=False)
    monkeypatch.setattr(
        knowledge_graph_module, "create_chat_model", lambda *_a, **_k: called.append(True)
    )
    graph = _rewrite_graph(tmp_path)
    state = {
        "rewrite": True,
        "normalized_query": NormalizedQuery(raw="hi", text="hi", language="en"),
    }
    # Guard must short-circuit before any model call when the model can't do structured output.
    assert await graph.rewrite_query(state) == {}
    assert called == []


@pytest.mark.asyncio
async def test_rewrite_query_applies_llm_rewrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeStructured:
        async def ainvoke(self, _messages):
            return {
                "parsed": QueryRewrite(standalone_query="what does the Research agent do?", keywords=["Selim"]),
                "raw": AIMessage(content=""),
            }

    class _FakeModel:
        def with_structured_output(self, _schema, include_raw=False):
            return _FakeStructured()

    _patch_rewrite_llm(monkeypatch)
    monkeypatch.setattr(knowledge_graph_module, "create_chat_model", lambda *_a, **_k: _FakeModel())
    graph = _rewrite_graph(tmp_path)
    state = {
        "rewrite": True,
        "normalized_query": NormalizedQuery(raw="teh 2nd one", text="teh 2nd one", language="en"),
    }
    result = await graph.rewrite_query(state)
    assert result["rewritten_query"] == "what does the Research agent do?"
    assert result["rewrite_keywords"] == ["Selim"]
    assert result["normalized_query"].text == "what does the Research agent do?"
    # Original raw + detected language are preserved (answer-language policy follows the user).
    assert result["normalized_query"].raw == "teh 2nd one"
    assert result["normalized_query"].language == "en"


@pytest.mark.asyncio
async def test_rewrite_query_blank_output_falls_back_to_normalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _FakeStructured:
        async def ainvoke(self, _messages):
            return {"parsed": QueryRewrite(standalone_query="   ", keywords=["  "]), "raw": AIMessage(content="")}

    class _FakeModel:
        def with_structured_output(self, _schema, include_raw=False):
            return _FakeStructured()

    _patch_rewrite_llm(monkeypatch)
    monkeypatch.setattr(knowledge_graph_module, "create_chat_model", lambda *_a, **_k: _FakeModel())
    graph = _rewrite_graph(tmp_path)
    state = {
        "rewrite": True,
        "normalized_query": NormalizedQuery(raw="keep me", text="keep me", language="en"),
    }
    result = await graph.rewrite_query(state)
    assert result["rewritten_query"] == "keep me"
    assert result["rewrite_keywords"] == []


@pytest.mark.asyncio
async def test_rewrite_query_falls_back_when_structured_output_unparsable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: with_structured_output(include_raw=True) returns parse failures in the dict
    # (it does NOT raise). A reasoning model that hits MAX_TOKENS yields parsed=None — the node
    # must fall back to the raw query rather than silently doing nothing unlogged.
    class _FakeStructured:
        async def ainvoke(self, _messages):
            return {
                "parsed": None,
                "parsing_error": ValueError("Invalid json output: Here is the JSON requested:"),
                "raw": AIMessage(
                    content="Here is the JSON requested:",
                    response_metadata={"finish_reason": "MAX_TOKENS"},
                    usage_metadata={"input_tokens": 91, "output_tokens": 252, "total_tokens": 343},
                ),
            }

    class _FakeModel:
        def with_structured_output(self, _schema, include_raw=False):
            return _FakeStructured()

    _patch_rewrite_llm(monkeypatch)
    monkeypatch.setattr(knowledge_graph_module, "create_chat_model", lambda *_a, **_k: _FakeModel())
    graph = _rewrite_graph(tmp_path)
    state = {
        "rewrite": True,
        "normalized_query": NormalizedQuery(raw="طيب", text="طيب", language="ar"),
    }
    # Falls back to the raw query (empty delta), and does not raise.
    assert await graph.rewrite_query(state) == {}


@pytest.mark.asyncio
async def test_rewrite_query_falls_back_on_model_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("provider down")

    _patch_rewrite_llm(monkeypatch)
    monkeypatch.setattr(knowledge_graph_module, "create_chat_model", boom)
    graph = _rewrite_graph(tmp_path)
    state = {
        "rewrite": True,
        "normalized_query": NormalizedQuery(raw="hi", text="hi", language="en"),
    }
    # A model failure must never block retrieval — the node returns an empty passthrough.
    assert await graph.rewrite_query(state) == {}


@pytest.mark.asyncio
async def test_preview_file_markdown_and_unsupported(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    note = docs / "nested" / "note.md"
    note.parent.mkdir()
    note.write_text("# Title\n\nBody text.", encoding="utf-8")
    blocked = docs / "data.bin"
    blocked.write_bytes(b"\xff\xfe")

    service = KnowledgeService(tmp_path / "workspace", embedder=FakeEmbedder(), sparse_embedder=FakeSparseEmbedder())
    try:
        preview = await service.preview_file(str(note))
        assert preview.format == "markdown"
        assert preview.supported is True
        assert preview.content == "# Title\n\nBody text."
        assert preview.line_count == 3
        assert preview.character_count == len(preview.content or "")
        assert preview.estimated_tokens >= 1

        blocked_preview = await service.preview_file(str(blocked))
        assert blocked_preview.format == "unsupported"
        assert blocked_preview.supported is False
        assert blocked_preview.content is None
    finally:
        await service.close()
