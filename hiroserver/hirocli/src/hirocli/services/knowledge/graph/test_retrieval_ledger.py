"""Tests for the retrieval ledger — the priced ``rerank`` roll-up on the fact-search row.

At the ``ledger`` observability tier the graphiti fact-search renders as its single Graph-Runs
node plus (when a catalogued cross-encoder ran) ONE priced ``rerank`` roll-up child carrying the
model + processed tokens. RRF/MMR / local rerankers add no child. The deep per-stage breakdown
lives only in the ``trace`` sidecar (not exercised here). We open a real ``LedgerEntry``, flush,
write rows, and read ``logs/graph.log``. No graphiti, no network. (docs §12.2)
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest

from hiro_commons.log import Logger
from hirocli.runtime.agent_graph.ledger import LedgerSink
from hirocli.services.knowledge.graph.graphiti_search import GraphitiExpansion, RankedFact
from hirocli.services.knowledge.graph.ledger_tracer import RerankUsage
from hirocli.services.knowledge.graph.retrieval_ledger import flush_graph_expand

_GE = "knowledge/graph_expand"


@pytest.fixture(autouse=True)
def _setup_logger() -> Any:
    LedgerSink._opened.clear()
    Logger.set_level("INFO")
    Logger.setup(console=False)
    yield
    LedgerSink._opened.clear()


def _expansion() -> GraphitiExpansion:
    return GraphitiExpansion(
        chunk_ids=("c1", "c2", "c3"),
        facts=("Adam—WORKS_AT→Cedar Labs",),
        facts_total=8,
        facts_used=6,
        ranked=(
            RankedFact("Adam—WORKS_AT→Cedar Labs", valid_at="2024-08", chunk_id="8628aaaa"),
            RankedFact("Adam—WORKS_AT→Brightloom", valid_at="2024-01", chunk_id="bbbb"),
        ),
    )


def _flush_and_read(
    tmp_path: Path, rerank_usage: RerankUsage | None
) -> dict[str, dict[str, str]]:
    sink = LedgerSink(tmp_path)
    entry = sink.open_entry(_GE, {}, None, captures=frozenset({"decision"}))
    flush_graph_expand(entry, _expansion(), rerank_usage=rerank_usage)
    sink.write_rows(entry.rows(include_parent=True))
    with (tmp_path / "logs" / "graph.log").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return {r["node"]: r for r in rows if r["row_kind"] == "node"}


def test_cloud_rerank_emits_one_priced_rollup(tmp_path: Path) -> None:
    """A catalogued cloud reranker → ONE ``rerank`` child with provider/model/tokens + a real
    cost, nested under the parent. No other sub-steps."""
    usage = RerankUsage(
        model_id="voyage:rerank-2.5", processed_tokens=5000, calls=1, elapsed_ms=42.0
    )
    by_node = _flush_and_read(tmp_path, usage)

    rerank = by_node.get(f"{_GE}/rerank")
    assert rerank is not None, "priced rerank roll-up child should be spawned"
    assert rerank["provider"] == "voyage"
    assert rerank["model"] == "voyage:rerank-2.5"  # FULL prefixed id → catalog resolves + prices
    assert rerank["input_tokens"] == "5000"
    assert rerank["cost_usd"] not in ("", "0")  # a real, non-zero cost
    assert rerank["pricing_version"] != ""
    assert rerank["sub_step"] not in ("", None)  # nests under graph_expand (2-level)
    # The ONLY child is the rerank roll-up — no embed_query/candidate_gen/bfs_expand/etc.
    children = [n for n in by_node if n.startswith(f"{_GE}/")]
    assert children == [f"{_GE}/rerank"], children


def test_no_rerank_no_child(tmp_path: Path) -> None:
    """RRF/MMR (no rerank usage) → no children at all; the parent stands alone."""
    by_node = _flush_and_read(tmp_path, None)
    assert [n for n in by_node if n.startswith(f"{_GE}/")] == []

    # An empty accumulator (cross-encoder wired but never called) is also no-op.
    by_node_empty = _flush_and_read(tmp_path, RerankUsage())
    assert [n for n in by_node_empty if n.startswith(f"{_GE}/")] == []


def test_local_reranker_priced_free(tmp_path: Path) -> None:
    """A local reranker id misses the catalog → the row still renders, priced at $0 (free)."""
    usage = RerankUsage(
        model_id="flashrank:ms-marco-MiniLM", processed_tokens=4000, calls=1, elapsed_ms=12.0
    )
    by_node = _flush_and_read(tmp_path, usage)
    rerank = by_node[f"{_GE}/rerank"]
    assert rerank["model"] == "flashrank:ms-marco-MiniLM"
    assert rerank["cost_usd"] == "0"  # not in catalog → calculated free, not blank
