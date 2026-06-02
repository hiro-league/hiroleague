"""Bootstrap tests for GraphitiMemoryService.

Exercises REAL Graphiti + Kuzu construction and ``build_indices_and_constraints``
against a temp DB (no network). The LLM/embedder are stubs that assert they are
never called during bootstrap/init — only the driver should be touched.
"""

from __future__ import annotations

import typing

import pytest
from graphiti_core.embedder.client import EmbedderClient
from graphiti_core.llm_client.client import LLMClient
from graphiti_core.llm_client.config import LLMConfig, ModelSize
from graphiti_core.prompts.models import Message
from pydantic import BaseModel

from hirocli.domain.preferences import WorkspacePreferences
from hirocli.services.knowledge.graph.graphiti_service import (
    GraphitiMemoryService,
    graphiti_db_path,
    read_graph_snapshot,
)


class _StubLLM(LLMClient):
    def __init__(self) -> None:
        super().__init__(LLMConfig())

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = 1024,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, typing.Any]:
        raise AssertionError("LLM must not be called during bootstrap/init")


class _StubEmbedder(EmbedderClient):
    async def create(self, input_data: typing.Any) -> list[float]:
        raise AssertionError("embedder must not be called during bootstrap/init")


@pytest.mark.asyncio
async def test_bootstrap_initializes_against_real_kuzu(tmp_path) -> None:
    db = graphiti_db_path(tmp_path)
    svc = GraphitiMemoryService(db_path=db, llm_client=_StubLLM(), embedder=_StubEmbedder())
    try:
        await svc.initialize()
        assert svc.graphiti is not None
        assert db.parent.exists()  # workspace/knowledge/graph/ created
        # initialize is idempotent
        await svc.initialize()
    finally:
        await svc.close()
    # close is idempotent
    await svc.close()


def test_from_preferences_none_when_backend_off(tmp_path) -> None:
    prefs = WorkspacePreferences()  # backend defaults to "off"
    assert GraphitiMemoryService.from_preferences(prefs, tmp_path) is None


def test_from_preferences_none_when_no_model(tmp_path) -> None:
    prefs = WorkspacePreferences()
    prefs.knowledge.graph.backend = "graphiti"
    # No llm.default_chat and no knowledge.answering.model → extraction resolves
    # None (before any catalog/credential lookup) → service not created.
    assert GraphitiMemoryService.from_preferences(prefs, tmp_path, workspace_id="w") is None


@pytest.mark.asyncio
async def test_snapshot_empty_when_no_db(tmp_path) -> None:
    # No graph built → empty, and no DB file created (read must not have side effects).
    db = graphiti_db_path(tmp_path)
    nodes, edges = await read_graph_snapshot(db)
    assert nodes == []
    assert edges == []
    assert not db.exists()


@pytest.mark.asyncio
async def test_snapshot_empty_graph_against_real_kuzu(tmp_path) -> None:
    # Build an empty graph (schema only), then snapshot → empty lists. Validates the
    # EntityNode/EntityEdge.get_by_group_ids read path against real Kuzu.
    db = graphiti_db_path(tmp_path)
    svc = GraphitiMemoryService(db_path=db, llm_client=_StubLLM(), embedder=_StubEmbedder())
    try:
        await svc.initialize()
    finally:
        await svc.close()
    nodes, edges = await read_graph_snapshot(db)
    assert nodes == []
    assert edges == []
