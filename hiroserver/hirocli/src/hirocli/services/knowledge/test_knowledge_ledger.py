from __future__ import annotations

import asyncio
import csv
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from hiro_commons.log import Logger
from hirocli.domain.preferences import ResolvedModel, WorkspacePreferences
from hirocli.runtime.agent_graph.ledger import (
    LedgerSink,
    RunAccumulator,
    current_run,
)
from hirocli.services.knowledge.agent.graph import KnowledgeAgentGraph
from hirocli.services.knowledge.ledger_runner import (
    KNOWLEDGE_RUN_ID_PREFIX,
    finalize_standalone_run,
    knowledge_answer_ledger,
    preview_query,
)
from hirocli.services.knowledge.service import KnowledgeService


@pytest.fixture(autouse=True)
def _setup_logger() -> None:
    LedgerSink._opened.clear()
    Logger.set_level("INFO")
    Logger.setup(console=False)
    yield
    LedgerSink._opened.clear()


def _graph_log_path(workspace: Path) -> Path:
    return workspace / "logs" / "graph.log"


def _read_rows(workspace: Path) -> list[dict[str, str]]:
    path = _graph_log_path(workspace)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class FakeRetrievalService:
    async def embed_query(self, query: str) -> list[float]:
        return [0.2] * 8

    async def embed_query_sparse(self, query: str):
        return ([0], [1.0])

    async def vector_search_by_vector(self, vector: list[float], sparse_vector=None, **kwargs) -> list:
        if not vector:
            return []
        from hirocli.services.knowledge.models import KnowledgeSearchHit

        return [
            KnowledgeSearchHit(
                document_id="doc-1",
                point_id="pt-1",
                score=0.91,
                ord=0,
                text="Indexed chunk text.",
                heading_path="Intro",
                title="Doc",
                source_uri="file:///note.md",
                owner_kind="system",
                owner_id="0",
                category_id=None,
                subcategory_id=None,
                tags=[],
            )
        ]


@pytest.mark.asyncio
async def test_knowledge_graph_writes_ledger_rows_for_standalone_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"

    class FakeModel:
        async def ainvoke(self, messages):
            return AIMessage(content="Ledger answer.")

    monkeypatch.setattr(
        "hirocli.services.knowledge.agent.graph.create_chat_model",
        lambda *_args, **_kwargs: FakeModel(),
    )
    monkeypatch.setattr(
        "hirocli.services.knowledge.agent.graph.resolve_knowledge_answering_llm",
        lambda *_args, **_kwargs: ResolvedModel(
            model_id="fake:model",
            temperature=0.2,
            max_tokens=800,
        ),
    )

    graph_builder = KnowledgeAgentGraph(
        workspace_path=workspace,
        service=FakeRetrievalService(),
        prefs=WorkspacePreferences(),
    )
    graph = graph_builder.build()
    query = "What is indexed?"

    run_id = ""
    async with knowledge_answer_ledger(sink=graph_builder._ledger_sink, query=query) as ledger_run:
        assert ledger_run.nested is False
        assert ledger_run.run_id.startswith(KNOWLEDGE_RUN_ID_PREFIX)
        run_id = ledger_run.run_id
        state = await graph.ainvoke(
            {"query": query, "filters": {}, "top_k": 5, "min_score": 0.0},
            config=ledger_run.runnable_config,
        )
        finalize_standalone_run(
            ledger_run.accumulator,
            query=query,
            answer=str(state.get("answer") or ""),
            no_results=bool(state.get("no_results")),
        )

    rows = _read_rows(workspace)
    run_rows = [row for row in rows if row.get("row_kind") == "run"]
    node_rows = [row for row in rows if row.get("row_kind") == "node"]
    assert len(run_rows) == 1
    assert run_rows[0]["run_id"] == run_id
    assert preview_query(query) in str(run_rows[0].get("input_preview") or "")
    assert all(row["run_id"] == run_id for row in node_rows)
    assert any(row["node"] == "knowledge/embed_query" for row in node_rows)
    assert any(row["node"] == "knowledge/vector_search" for row in node_rows)
    assert any(row["node"] == "knowledge/call_model" for row in node_rows)
    assert current_run.get() is None


@pytest.mark.asyncio
async def test_knowledge_graph_nests_under_parent_run_without_aggregate_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    parent_run_id = "chat-msg-123"
    sink = LedgerSink(workspace)
    parent = RunAccumulator(
        sink=sink,
        run_id=parent_run_id,
        inbound_id="msg-123",
        character_id="char-1",
    )
    token = current_run.set(parent)

    class FakeModel:
        async def ainvoke(self, messages):
            return AIMessage(content="Nested answer.")

    monkeypatch.setattr(
        "hirocli.services.knowledge.agent.graph.create_chat_model",
        lambda *_args, **_kwargs: FakeModel(),
    )
    monkeypatch.setattr(
        "hirocli.services.knowledge.agent.graph.resolve_knowledge_answering_llm",
        lambda *_args, **_kwargs: ResolvedModel(
            model_id="fake:model",
            temperature=0.2,
            max_tokens=800,
        ),
    )

    graph_builder = KnowledgeAgentGraph(
        workspace_path=workspace,
        service=FakeRetrievalService(),
        prefs=WorkspacePreferences(),
    )
    graph = graph_builder.build()

    try:
        async with knowledge_answer_ledger(sink=sink, query="nested?") as ledger_run:
            assert ledger_run.nested is True
            assert ledger_run.run_id == parent_run_id
            assert ledger_run.accumulator is None
            await graph.ainvoke(
                {
                    "query": "nested?",
                    "filters": {},
                    "top_k": 3,
                    "min_score": 0.0,
                    **{
                        "inbound_id": parent.inbound_id,
                        "character_id": parent.character_id,
                    },
                },
                config=ledger_run.runnable_config,
            )
    finally:
        current_run.reset(token)

    rows = _read_rows(workspace)
    assert not any(row.get("row_kind") == "run" for row in rows)
    node_rows = [row for row in rows if row.get("row_kind") == "node"]
    assert node_rows
    assert all(row["run_id"] == parent_run_id for row in node_rows)
    assert any(row["node"].startswith("knowledge/") for row in node_rows)


@pytest.mark.asyncio
async def test_service_answer_writes_standalone_run_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"

    class StubKnowledgeService(KnowledgeService):
        def __init__(self, workspace_path: Path) -> None:
            self.workspace_path = workspace_path
            self._closed = False

        def workspace_prefs(self) -> WorkspacePreferences:
            return WorkspacePreferences()

        async def close(self) -> None:
            self._closed = True

    class FakeModel:
        async def ainvoke(self, messages):
            return AIMessage(content="Service answer.")

    monkeypatch.setattr(
        "hirocli.services.knowledge.agent.graph.create_chat_model",
        lambda *_args, **_kwargs: FakeModel(),
    )
    monkeypatch.setattr(
        "hirocli.services.knowledge.agent.graph.resolve_knowledge_answering_llm",
        lambda *_args, **_kwargs: ResolvedModel(
            model_id="fake:model",
            temperature=0.2,
            max_tokens=800,
        ),
    )
    monkeypatch.setattr(
        StubKnowledgeService,
        "embed_query",
        FakeRetrievalService.embed_query,
    )
    monkeypatch.setattr(
        StubKnowledgeService,
        "embed_query_sparse",
        FakeRetrievalService.embed_query_sparse,
    )
    monkeypatch.setattr(
        StubKnowledgeService,
        "vector_search_by_vector",
        FakeRetrievalService.vector_search_by_vector,
    )

    service = StubKnowledgeService(workspace)
    try:
        result = await service.answer("service ledger?")
        assert result.answer == "Service answer."
    finally:
        await service.close()

    rows = _read_rows(workspace)
    run_rows = [row for row in rows if row.get("row_kind") == "run"]
    assert len(run_rows) == 1
    assert str(run_rows[0]["run_id"]).startswith(KNOWLEDGE_RUN_ID_PREFIX)
    assert "service ledger?" in str(run_rows[0].get("input_preview") or "")
