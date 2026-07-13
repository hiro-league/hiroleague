"""Tests for the ingest-ledger roll-up (§12.2 observability refactor).

At the ``ledger`` tier, one ``add_episode``'s internal graphiti LLM work is rolled up onto the
SINGLE ``episode`` row (priced) — there are NO per-operation sub-rows anymore (that breakdown
moved to the ``trace`` sidecar). The roll-up total equals the sum of the per-op usage fed by the
adapter sinks, so the run aggregate cost is unchanged.

The fake ``add_episode`` fires the adapter usage/embed sinks like a real internal pass AND appends
an ``add_episode`` ``SpanRecord`` to ``current_spans`` (what the ``LedgerTracer`` does live) so the
supersession count surfaces. No Kuzu/LLM.
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
# Totals the fake feeds (extract_entities + extract_edges + 2× EdgeDuplicate):
_TOTAL_IN = 100 + 80 + 30 + 28  # 238
_TOTAL_OUT = 20 + 15 + 5 + 6  # 46
_EPISODE = "graphiti_ingest/episode"


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


def _rows(tmp_path: Path) -> list[dict[str, str]]:
    with (tmp_path / "logs" / "graph.log").open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.mark.asyncio
async def test_episode_row_carries_rolled_up_usage_and_prices(tmp_path: Path) -> None:
    await ingest_episodes(
        _FakeGraphiti(), [_ep()], source_role="user_document", group_id="kb_main",
        ledger_sink=LedgerSink(tmp_path),
    )
    rows = _rows(tmp_path)
    by_node = {r["node"]: r for r in rows if r["row_kind"] == "node"}

    # The episode row carries the ROLLED-UP usage of all internal LLM ops, and prices.
    episode = by_node[_EPISODE]
    assert episode["provider"] == "google"
    assert episode["model"] == _MODEL
    assert episode["input_tokens"] == str(_TOTAL_IN)
    assert episode["output_tokens"] == str(_TOTAL_OUT)
    assert episode["cost_usd"] not in ("", "0")
    assert episode["pricing_version"] != ""

    # NO per-operation sub-rows anymore (they moved to the trace sidecar).
    children = [n for n in by_node if n.startswith("graphiti_ingest/") and n != _EPISODE]
    assert children == [], children

    # The roll-up summary preview still surfaces structure (entities/facts/invalidated/tokens).
    prev = episode["output_preview"]
    assert "1 invalidated" in prev
    assert "llm=4 calls" in prev
    assert f"{_TOTAL_IN}i/{_TOTAL_OUT}o" in prev


@pytest.mark.asyncio
async def test_run_aggregate_cost_equals_episode_cost(tmp_path: Path) -> None:
    """Cost-fold guarantee: rolling N per-op costs onto one episode row doesn't change the sum —
    the ``@run`` aggregate cost equals the episode row's cost (both non-zero)."""
    await ingest_episodes(
        _FakeGraphiti(), [_ep()], source_role="user_document", group_id="kb_main",
        ledger_sink=LedgerSink(tmp_path),
    )
    rows = _rows(tmp_path)
    episode = next(r for r in rows if r["node"] == _EPISODE and r["row_kind"] == "node")
    run = next(r for r in rows if r["row_kind"] == "run")
    assert float(episode["cost_usd"]) > 0
    assert float(run["cost_usd"]) == pytest.approx(float(episode["cost_usd"]))
