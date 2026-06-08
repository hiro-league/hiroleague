"""Tests for the retrieval-trace model + JSONL sidecar (no graphiti, no DB)."""

from __future__ import annotations

import datetime as dt

from hirocli.services.knowledge.graph.retrieval_trace import (
    TRACE_SCHEMA_VERSION,
    RetrievalTrace,
    StageRecord,
    _edge_brief,
    read_trace_sidecar,
    write_trace_sidecar,
)


class _Edge:
    def __init__(self, uuid, fact, *, name="", episodes=None, invalid_at=None, expired_at=None):
        self.uuid = uuid
        self.fact = fact
        self.name = name
        self.source_node_uuid = "s"
        self.target_node_uuid = "t"
        self.episodes = episodes or []
        self.valid_at = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
        self.invalid_at = invalid_at
        self.expired_at = expired_at


def test_edge_brief_serializes_temporal_and_score() -> None:
    brief = _edge_brief(_Edge("e1", "Adam works at Cedar", episodes=["c1", "c2"]), score=0.5)
    assert brief["uuid"] == "e1"
    assert brief["fact"] == "Adam works at Cedar"
    assert brief["episodes"] == ["c1", "c2"]
    assert brief["valid_at"].startswith("2024-01-01")
    assert brief["invalid_at"] is None
    assert brief["score"] == 0.5


def test_edge_brief_score_none_by_default() -> None:
    assert _edge_brief(_Edge("e1", "f"))["score"] is None


def test_sidecar_roundtrip_keeps_step_linkage(tmp_path) -> None:
    trace = RetrievalTrace(
        query="where does adam live",
        group_id="kb_main",
        recipe="rrf",
        temporal="current",
        num_results=10,
        sim_min_score=0.3,
        k_hop=1,
    )
    trace.add_stage(
        StageRecord(kind="candidate", label="Keyword leg · BM25", items=[_edge_brief(_Edge("e1", "f"))])
    )
    write_trace_sidecar(tmp_path, run_id="chat-42", step_index=4, trace=trace)

    records = read_trace_sidecar(tmp_path, "chat-42")
    assert len(records) == 1
    rec = records[0]
    assert rec["run_id"] == "chat-42"
    assert rec["step_index"] == 4
    assert rec["schema_version"] == TRACE_SCHEMA_VERSION
    assert rec["query"] == "where does adam live"
    assert rec["stages"][0]["kind"] == "candidate"
    assert rec["stages"][0]["items"][0]["uuid"] == "e1"


def test_sidecar_appends_multiple_searches(tmp_path) -> None:
    for step in (4, 7):
        t = RetrievalTrace(
            query=f"q{step}",
            group_id="kb_main",
            recipe="rrf",
            temporal="current",
            num_results=5,
            sim_min_score=0.3,
            k_hop=1,
        )
        write_trace_sidecar(tmp_path, run_id="chat-1", step_index=step, trace=t)
    records = read_trace_sidecar(tmp_path, "chat-1")
    assert [r["step_index"] for r in records] == [4, 7]


def test_read_missing_sidecar_is_empty(tmp_path) -> None:
    assert read_trace_sidecar(tmp_path, "nope") == []


def test_read_skips_malformed_line(tmp_path) -> None:
    from hirocli.services.knowledge.graph.retrieval_trace import trace_dir

    directory = trace_dir(tmp_path)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chat-9.jsonl").write_text(
        '{"run_id": "chat-9", "step_index": 1, "stages": []}\nnot-json\n', encoding="utf-8"
    )
    records = read_trace_sidecar(tmp_path, "chat-9")
    assert len(records) == 1  # malformed tail skipped, valid line kept
