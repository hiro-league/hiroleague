"""Tests for the §12.2 ingest-ledger deltas: per-edge ``resolve_facts`` (Hybrid),
content previews, ``edge.invalidated_count`` (from the add_episode tracer span), and
the ``compact`` collapse.

The fake ``add_episode`` fires the adapter usage/embed sinks like a real internal
pass AND appends an ``add_episode`` ``SpanRecord`` to ``current_spans`` (what the
``LedgerTracer`` does live) so the supersession count surfaces. No Kuzu/LLM.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from hiro_commons.log import Logger
from hirocli.runtime.agent_graph.ledger import LedgerSink
from hirocli.services.knowledge.graph.graphiti_adapters import GraphitiLLMUsage
from hirocli.services.knowledge.graph.graphiti_ingest import (
    GraphitiEpisodeInput,
    ingest_episodes,
)
from hirocli.services.knowledge.graph.ingest_ledger import (
    record_episode_embed,
    record_episode_llm_usage,
)
from hirocli.services.knowledge.graph.ledger_tracer import SpanRecord, current_spans

_MODEL = "google:gemini-3-flash-preview"


class _Result:
    def __init__(self, node_names: list[str], edge_facts: list[str]) -> None:
        self.nodes = [type("N", (), {"name": n})() for n in node_names]
        self.edges = [type("E", (), {"fact": f})() for f in edge_facts]


class _FakeGraphiti:
    """Two extracted edges → two ``resolve_facts`` calls; one supersedes a prior fact."""

    async def add_episode(self, **kwargs: Any) -> _Result:
        record_episode_llm_usage(
            GraphitiLLMUsage(
                _MODEL, "medium", 100, 20, operation="ExtractedEntities", elapsed_ms=12.0,
                preview="extracted_entities[2]: Adam, Cedar Labs",
            )
        )
        record_episode_llm_usage(
            GraphitiLLMUsage(
                _MODEL, "medium", 80, 15, operation="ExtractedEdges", elapsed_ms=8.0,
                preview="edges[2]: Adam—WORKS_AT→Cedar Labs",
            )
        )
        # Per-edge resolve (graphiti semaphore_gathers resolve_edge): two calls.
        record_episode_llm_usage(
            GraphitiLLMUsage(
                _MODEL, "medium", 30, 5, operation="EdgeDuplicate", elapsed_ms=3.0,
                preview="Adam—WORKS_AT→Cedar Labs new",
            )
        )
        record_episode_llm_usage(
            GraphitiLLMUsage(
                _MODEL, "medium", 28, 6, operation="EdgeDuplicate", elapsed_ms=3.0,
                preview="Adam—WORKS_AT→Brightloom INVALIDATE",
            )
        )
        record_episode_embed(3, 2.0)
        # Simulate the add_episode tracer span (the supersession count).
        buf = current_spans.get()
        if buf is not None:
            buf.append(
                SpanRecord(
                    name="add_episode",
                    attributes={"edge.invalidated_count": 1, "node.count": 3, "edge.count": 1},
                )
            )
        return _Result(["Adam", "Cedar Labs", "Brightloom"], ["Adam—WORKS_AT→Cedar Labs"])

    async def build_indices_and_constraints(self, delete_existing: bool = False) -> None:
        return None


@pytest.fixture(autouse=True)
def _setup_logger() -> Any:
    LedgerSink._opened.clear()
    Logger.set_level("INFO")
    Logger.setup(console=False)
    yield
    LedgerSink._opened.clear()


def _ep() -> GraphitiEpisodeInput:
    return GraphitiEpisodeInput(
        chunk_id="ep_022",
        document_id="adam_year",
        text="I left Brightloom and start at Cedar Labs.",
        reference_time=dt.datetime(2024, 8, 12, tzinfo=dt.UTC),
        document_title="Adam's Year",
    )


def _nodes(tmp_path: Path) -> dict[str, dict[str, str]]:
    path = tmp_path / "logs" / "graph.log"
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return {r["node"]: r for r in rows if r["row_kind"] == "node"}


@pytest.mark.asyncio
async def test_rich_renders_per_edge_resolve_facts_and_previews(tmp_path: Path) -> None:
    await ingest_episodes(
        _FakeGraphiti(), [_ep()], source_role="user_document", group_id="kb_main",
        ledger_sink=LedgerSink(tmp_path), ledger_detail="rich",
    )
    by_node = _nodes(tmp_path)

    # Two edges → two per-item resolve_facts rows, each with its own decision preview.
    r1 = by_node["knowledge_graph_ingest/resolve_facts[1]"]
    r2 = by_node["knowledge_graph_ingest/resolve_facts[2]"]
    assert "new" in r1["output_preview"]
    assert "INVALIDATE" in r2["output_preview"]
    # Aggregate (single) row is NOT used when there are 2+ edges.
    assert "knowledge_graph_ingest/resolve_facts" not in by_node

    # Content preview rides on the extract nodes (what they produced).
    assert "Adam" in by_node["knowledge_graph_ingest/extract_entities"]["output_preview"]
    assert "Cedar Labs" in by_node["knowledge_graph_ingest/extract_facts"]["output_preview"]

    # edge.invalidated_count from the add_episode span surfaces on episode + persist.
    episode = by_node["knowledge_graph_ingest/episode"]
    assert "1 invalidated" in episode["output_preview"]
    assert "invalidated=1" in by_node["knowledge_graph_ingest/persist"]["output_preview"]


@pytest.mark.asyncio
async def test_compact_aggregates_resolve_facts_and_drops_previews(tmp_path: Path) -> None:
    await ingest_episodes(
        _FakeGraphiti(), [_ep()], source_role="user_document", group_id="kb_main",
        ledger_sink=LedgerSink(tmp_path), ledger_detail="compact",
    )
    by_node = _nodes(tmp_path)

    # One aggregate resolve_facts row (calls=2), no per-item rows.
    agg = by_node["knowledge_graph_ingest/resolve_facts"]
    assert "calls=2" in agg["output_preview"]
    assert "knowledge_graph_ingest/resolve_facts[1]" not in by_node
    # Compact omits the content previews on the op rows (stats only).
    assert "Cedar Labs" not in by_node["knowledge_graph_ingest/extract_facts"]["output_preview"]
    # The invalidated rollup is still shown (it's structural, not verbose).
    assert "1 invalidated" in by_node["knowledge_graph_ingest/episode"]["output_preview"]
