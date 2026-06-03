"""Tests for the retrieval ledger — ``graph_expand`` unfolded into search sub-steps.

``flush_graph_expand`` turns buffered graphiti ``search.*`` spans + the
``GraphitiExpansion`` result into one flattened level of sub-step rows under the
``graph_expand`` entry. We open a real ``LedgerEntry``, flush, write rows, and read
``logs/graph.log``. No graphiti, no network. (docs §12.2.2)
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest

from hiro_commons.log import Logger
from hirocli.runtime.agent_graph.ledger import LedgerSink
from hirocli.services.knowledge.graph.graphiti_search import GraphitiExpansion, RankedFact
from hirocli.services.knowledge.graph.ledger_tracer import SpanRecord
from hirocli.services.knowledge.graph.retrieval_ledger import flush_graph_expand

_GE = "knowledge/graph_expand"


@pytest.fixture(autouse=True)
def _setup_logger() -> Any:
    LedgerSink._opened.clear()
    Logger.set_level("INFO")
    Logger.setup(console=False)
    yield
    LedgerSink._opened.clear()


def _spans() -> list[SpanRecord]:
    return [
        SpanRecord("search.embed_query_vector", {"query_vector.dimension": 1024}, 41.0),
        SpanRecord(
            "search.edge_search.execute_methods",
            {"result_set_count": 2, "non_empty_result_sets": 2},
            96.0,
        ),
        SpanRecord("search.edge_search.expand_bfs", {}, 28.0),
        SpanRecord("search.edge_search.seed_rrf", {"candidate_count": 14}, 3.0),
        SpanRecord(
            "search.edge_search.rerank", {"candidate_count": 14, "reranked_count": 8}, 5.0
        ),
        SpanRecord("llm.generate", {}, 1.0),  # never mapped → ignored
    ]


def _expansion() -> GraphitiExpansion:
    return GraphitiExpansion(
        chunk_ids=("c1", "c2", "c3"),
        facts=("Adam—WORKS_AT→Cedar Labs",),
        facts_total=8,
        facts_used=6,
        ranked=(
            RankedFact("Adam—WORKS_AT→Cedar Labs", valid_at="2024-08", chunk_id="8628aaaa"),
            RankedFact(
                "Adam—WORKS_AT→Brightloom",
                valid_at="2024-01",
                invalid_at="2024-08",
                chunk_id="bbbb",
                superseded=True,
            ),
        ),
    )


def _flush_and_read(tmp_path: Path, detail: str) -> dict[str, dict[str, str]]:
    sink = LedgerSink(tmp_path)
    entry = sink.open_entry(_GE, {}, None, captures=frozenset({"decision"}))
    flush_graph_expand(entry, _spans(), _expansion(), temporal="current", ledger_detail=detail)
    sink.write_rows(entry.rows(include_parent=True))
    path = tmp_path / "logs" / "graph.log"
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return {r["node"]: r for r in rows if r["row_kind"] == "node"}


def test_rich_unfolds_search_into_substeps_with_ranked_facts(tmp_path: Path) -> None:
    by_node = _flush_and_read(tmp_path, "rich")

    # Every graphiti search phase + the temporal_filter wrapper renders.
    for node in (
        f"{_GE}/embed_query",
        f"{_GE}/candidate_gen",
        f"{_GE}/bfs_expand",
        f"{_GE}/rrf_fuse",
        f"{_GE}/rerank",
        f"{_GE}/temporal_filter",
    ):
        assert node in by_node, node

    # llm.generate was not mapped.
    assert f"{_GE}/llm.generate" not in by_node

    # Counts come from span attributes.
    assert "dim=1024" in by_node[f"{_GE}/embed_query"]["output_preview"]
    assert "methods=2" in by_node[f"{_GE}/candidate_gen"]["output_preview"]
    assert "14 → 8 kept" in by_node[f"{_GE}/rerank"]["output_preview"]

    # Ranked facts (text, not vectors) ride on the rerank node; superseded marked.
    rerank_preview = by_node[f"{_GE}/rerank"]["output_preview"]
    assert "Adam—WORKS_AT→Cedar Labs" in rerank_preview
    assert "⊘" in rerank_preview  # the superseded Brightloom fact

    # temporal_filter: current mode reports the query-level push-down (design §7);
    # the fixture's 1 superseded fact slipped past it and is defensively dropped —
    # labelled as such, never as the primary filter.
    tf = by_node[f"{_GE}/temporal_filter"]["output_preview"]
    assert "push-down" in tf
    assert "6 current facts" in tf
    assert "slipped past push-down" in tf
    assert "chunk_ids[3]" in tf


def test_compact_keeps_counts_drops_ranked_facts(tmp_path: Path) -> None:
    by_node = _flush_and_read(tmp_path, "compact")
    # Sub-steps still render (with counts)…
    assert f"{_GE}/rerank" in by_node
    assert "14 → 8 kept" in by_node[f"{_GE}/rerank"]["output_preview"]
    # …but the ranked fact list is omitted in compact.
    assert "Adam—WORKS_AT→Cedar Labs" not in by_node[f"{_GE}/rerank"]["output_preview"]


def test_substeps_nest_under_graph_expand(tmp_path: Path) -> None:
    by_node = _flush_and_read(tmp_path, "rich")
    # Children share the parent's step_index and carry a sub_step (2-level nesting).
    rerank = by_node[f"{_GE}/rerank"]
    assert rerank["sub_step"] not in ("", None)


def test_temporal_all_reports_history_not_dropped(tmp_path: Path) -> None:
    """temporal=all keeps superseded facts — the ledger must report them as *shown*,
    not *dropped* (the latent mislabel the §7 fix corrects)."""
    sink = LedgerSink(tmp_path)
    entry = sink.open_entry(_GE, {}, None, captures=frozenset({"decision"}))
    flush_graph_expand(entry, _spans(), _expansion(), temporal="all", ledger_detail="rich")
    sink.write_rows(entry.rows(include_parent=True))
    with (tmp_path / "logs" / "graph.log").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    by_node = {r["node"]: r for r in rows if r["row_kind"] == "node"}
    tf = by_node[f"{_GE}/temporal_filter"]["output_preview"]
    assert "history included" in tf
    assert "superseded shown" in tf
    assert "dropped" not in tf
