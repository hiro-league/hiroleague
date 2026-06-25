"""Unit tests for ``graphiti_session`` async context manager (P5)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hirocli.domain.preferences import WorkspacePreferences
from hirocli.services.knowledge.graph.graphiti_session import graphiti_session
from hirocli.services.knowledge.graph.ledger_tracer import current_rerank_usage
from hirocli.services.knowledge.graph.retrieval_trace import current_capture


class _FakeService:
    def __init__(self) -> None:
        self.close_calls = 0

    async def search_chunk_ids(
        self,
        query: str,
        *,
        num_results: int,
        temporal: str,
        k_hop: int | None = None,
        show_expiry: bool = False,
    ):
        return SimpleNamespace(
            chunk_ids=["c1"],
            facts=["fact"],
            facts_used=1,
            facts_total=1,
        )

    async def close(self) -> None:
        self.close_calls += 1


class _BoomService(_FakeService):
    async def search_chunk_ids(
        self,
        query: str,
        *,
        num_results: int,
        temporal: str,
        k_hop: int | None = None,
        show_expiry: bool = False,
    ):
        raise RuntimeError("search boom")


@pytest.mark.asyncio
async def test_graphiti_session_yields_none_when_service_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "hirocli.services.knowledge.graph.GraphitiMemoryService.from_preferences",
        lambda *a, **k: None,
    )
    prefs = WorkspacePreferences()

    async with graphiti_session(prefs, tmp_path) as session:
        assert session is None


@pytest.mark.asyncio
async def test_graphiti_session_resets_context_vars_and_closes_on_success(tmp_path: Path) -> None:
    fake = _FakeService()
    prefs = WorkspacePreferences()
    with patch(
        "hirocli.services.knowledge.graph.GraphitiMemoryService.from_preferences",
        return_value=fake,
    ):
        assert current_rerank_usage.get() is None
        assert current_capture.get() is None
        async with graphiti_session(prefs, tmp_path) as session:
            assert session is not None
            assert current_rerank_usage.get() is not None
            assert current_capture.get() is None
            expansion = await session.search_chunk_ids("q", num_results=3, temporal="current")
            assert expansion.chunk_ids == ["c1"]
        assert current_rerank_usage.get() is None
        assert current_capture.get() is None
        assert fake.close_calls == 1


@pytest.mark.asyncio
async def test_graphiti_session_closes_on_search_error(tmp_path: Path) -> None:
    fake = _BoomService()
    prefs = WorkspacePreferences()
    with patch(
        "hirocli.services.knowledge.graph.GraphitiMemoryService.from_preferences",
        return_value=fake,
    ):
        with pytest.raises(RuntimeError, match="search boom"):
            async with graphiti_session(prefs, tmp_path) as session:
                assert session is not None
                await session.search_chunk_ids("q", num_results=1, temporal="all")
        assert fake.close_calls == 1
        assert current_rerank_usage.get() is None


@pytest.mark.asyncio
async def test_graphiti_session_sets_capture_when_trace_enabled(tmp_path: Path) -> None:
    fake = _FakeService()
    prefs = WorkspacePreferences()
    prefs.graph.observability = "trace"
    with patch(
        "hirocli.services.knowledge.graph.GraphitiMemoryService.from_preferences",
        return_value=fake,
    ):
        async with graphiti_session(prefs, tmp_path) as session:
            assert session is not None
            assert current_capture.get() is session.capture
        assert current_capture.get() is None
