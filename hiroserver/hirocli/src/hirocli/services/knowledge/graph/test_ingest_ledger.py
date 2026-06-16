"""Tests for graph-ingest ledger instrumentation (roll-up model, §12.2 observability).

A fake Graphiti client simulates ``add_episode`` by firing the adapter usage/embed
sinks (``record_episode_llm_usage`` / ``record_episode_embed``) with canned
``GraphitiLLMUsage`` for each internal operation — exactly what the real
``GraphitiLLMClient`` does. We then read ``logs/graph.log`` and assert the run row plus
the SINGLE per-episode row carrying the rolled-up token usage (the per-operation
breakdown now lives only in the ``trace`` sidecar). No Kuzu, no network, no LLM.
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

_MODEL = "google:gemini-3-flash-preview"


class _Node:
    def __init__(self, name: str) -> None:
        self.name = name


class _Edge:
    def __init__(self, fact: str) -> None:
        self.fact = fact


class _Result:
    def __init__(self, node_names: list[str], edge_facts: list[str]) -> None:
        self.nodes = [_Node(n) for n in node_names]
        self.edges = [_Edge(f) for f in edge_facts]


class _FakeGraphiti:
    """add_episode fires the adapter sinks like a real internal Graphiti pass."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def add_episode(self, **kwargs: Any) -> _Result:
        self.calls.append(kwargs)
        # One LLM call per internal operation (medium tier), plus an embedder call.
        record_episode_llm_usage(
            GraphitiLLMUsage(_MODEL, "medium", 100, 20, operation="ExtractedEntities", elapsed_ms=12.0)
        )
        record_episode_llm_usage(
            GraphitiLLMUsage(_MODEL, "medium", 50, 10, operation="NodeResolutions", elapsed_ms=5.0)
        )
        record_episode_llm_usage(
            GraphitiLLMUsage(_MODEL, "medium", 80, 15, operation="ExtractedEdges", elapsed_ms=8.0)
        )
        record_episode_llm_usage(
            GraphitiLLMUsage(_MODEL, "medium", 30, 5, operation="EdgeDuplicate", elapsed_ms=3.0)
        )
        record_episode_embed(4, 2.0)
        return _Result(["Adam", "Nora", "Brightloom"], ["Adam—WORKS_AT→Brightloom"])

    async def build_indices_and_constraints(self, delete_existing: bool = False) -> None:
        return None

    async def close(self) -> None:  # pragma: no cover - trivial
        return None


@pytest.fixture(autouse=True)
def _setup_logger() -> Any:
    LedgerSink._opened.clear()
    Logger.set_level("INFO")
    Logger.setup(console=False)
    yield
    LedgerSink._opened.clear()


def _rows(tmp_path: Path) -> list[dict[str, str]]:
    path = tmp_path / "logs" / "graph.log"
    assert path.exists()
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.mark.asyncio
async def test_ingest_writes_run_and_per_operation_nodes(tmp_path: Path) -> None:
    g = _FakeGraphiti()
    eps = [
        GraphitiEpisodeInput(
            chunk_id="ep_001",
            document_id="adam_year",
            text="Adam started at Brightloom.",
            reference_time=dt.datetime(2024, 1, 15, tzinfo=dt.UTC),
            document_title="Adam's Year",
        )
    ]
    stats = await ingest_episodes(
        g, eps, source_role="user_document", group_id="kb_main", ledger_sink=LedgerSink(tmp_path)
    )
    assert stats.episodes_processed == 1

    rows = _rows(tmp_path)
    run_rows = [r for r in rows if r["row_kind"] == "run"]
    node_rows = [r for r in rows if r["row_kind"] == "node"]
    by_node = {r["node"]: r for r in node_rows}

    # --- aggregate @run row ------------------------------------------------
    assert len(run_rows) == 1
    run = run_rows[0]
    assert run["run_id"].startswith("knowledge_graph_ingest-")
    assert run["node"] == "@run"
    assert run["decision_detail"] == "graph_ingest"
    assert run["input_preview"].startswith("doc: 'Adam's Year'")
    assert "episodes=1/1" in run["output_preview"]
    # Tokens fold from the per-operation sub-steps (100+50+80+30 / 20+10+15+5).
    assert run["input_tokens"] == "260"
    assert run["output_tokens"] == "50"

    # --- per-episode parent step: carries the ROLLED-UP usage of all internal LLM ops ----
    episode = by_node["knowledge_graph_ingest/episode"]
    assert episode["step_index"] == "1"
    assert episode["sub_step"] == ""
    assert episode["model"] == _MODEL
    assert episode["provider"] == "google"
    assert episode["input_tokens"] == "260"  # 100+50+80+30 rolled onto the one episode row
    assert episode["output_tokens"] == "50"  # 20+10+15+5
    assert episode["input_preview"].startswith("episode 1/1 · chunk ep_001")
    # decision_detail now carries the readable turn id so the single-run table is scannable
    # by turn (the table renders this column but not input_preview).
    assert episode["decision_detail"] == "ep_001"
    assert "entities=3" in episode["output_preview"]
    assert "facts=1" in episode["output_preview"]
    assert "llm=4 calls" in episode["output_preview"]

    # --- NO per-operation / embed / persist sub-rows (the breakdown moved to the trace tier) ---
    assert [n for n in by_node if n.startswith("knowledge_graph_ingest/") and n
            != "knowledge_graph_ingest/episode"] == []


@pytest.mark.asyncio
async def test_rejected_role_still_writes_a_run_row(tmp_path: Path) -> None:
    g = _FakeGraphiti()
    eps = [GraphitiEpisodeInput(chunk_id="c1", document_id="d", text="x")]
    stats = await ingest_episodes(
        g, eps, source_role="retrieved_knowledge", ledger_sink=LedgerSink(tmp_path)
    )
    assert g.calls == []  # gate bailed before any add_episode
    assert stats.episodes_rejected == 1

    rows = _rows(tmp_path)
    run_rows = [r for r in rows if r["row_kind"] == "run"]
    assert len(run_rows) == 1
    assert run_rows[0]["status"] == "rejected"
    assert run_rows[0]["decision_detail"] == "rejected"
    # No episode/operation rows — nothing was ingested.
    assert [r for r in rows if r["row_kind"] == "node"] == []


@pytest.mark.asyncio
async def test_no_ledger_sink_is_silent(tmp_path: Path) -> None:
    """Without a sink the ingest still runs but writes no graph.log (tests/CLI path)."""
    g = _FakeGraphiti()
    eps = [GraphitiEpisodeInput(chunk_id="c1", document_id="d", text="hi")]
    stats = await ingest_episodes(g, eps, source_role="user_document", group_id="kb_main")
    assert stats.episodes_processed == 1
    assert not (tmp_path / "logs" / "graph.log").exists()
