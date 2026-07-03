"""Tests for agentic retrieval trace sidecar + ledger preview (P6, P9 event shapes)."""

from __future__ import annotations

import json
from pathlib import Path

from hirocli.services.memory.agent.agent_trace import (
    agent_trace_dir,
    build_retrieval_loop_payload,
    format_memory_recall_output_preview,
    read_agent_recall_result,
    read_agent_retrieval_trace,
    summarize_agent_transcript,
    write_agent_recall_result,
    write_agent_retrieval_trace,
)


def test_read_agent_retrieval_trace_round_trips_and_builds_payload(tmp_path) -> None:
    events = [
        {"event": "tool_call", "turn": 1, "sub_queries": 1, "cumulative_agent_turns": 1},
        {"event": "sub_result", "turn": 1, "sid": 1, "goal": "g", "query": "q", "returned": 2, "new": 2, "accumulated_total": 2},
        {"event": "final", "turn": 2, "cumulative_agent_turns": 2},
    ]
    write_agent_retrieval_trace(tmp_path, run_id="chat-1", slot="6", events=events)
    read = read_agent_retrieval_trace(tmp_path, "chat-1")
    assert [r["event"] for r in read] == ["tool_call", "sub_result", "final"]
    payload = build_retrieval_loop_payload(read, max_agent_turns=4)
    assert payload["turns"][0]["sub_queries"][0]["sid"] == 1
    assert read_agent_retrieval_trace(tmp_path, "missing-run") == []


def test_recall_result_companion_round_trips(tmp_path: Path) -> None:
    """The recalled-rows + draft-answer companion (feeds the chat detail dialog's Facts/Overview
    tabs) writes as ``{run}__{slot}.result.json`` and reads back by run_id — separate from the
    ``.jsonl`` transcript, so the transcript reader never picks it up."""
    recalled = [
        {"memory": "Budget is $50", "kind": "fact", "score": 0.9},
        {"memory": "Rex", "kind": "entity", "score": 0.7},
    ]
    write_agent_recall_result(
        tmp_path, run_id="chat-9", slot="6", recalled=recalled, answer="You said $50."
    )
    path = agent_trace_dir(tmp_path) / "chat-9__6.result.json"
    assert path.exists()
    data = read_agent_recall_result(tmp_path, "chat-9")
    assert data["answer"] == "You said $50."
    assert [r["kind"] for r in data["recalled"]] == ["fact", "entity"]
    # The transcript reader globs *.jsonl and must NOT surface the .result.json companion.
    assert read_agent_retrieval_trace(tmp_path, "chat-9") == []
    assert read_agent_recall_result(tmp_path, "missing-run") == {}


def test_build_retrieval_loop_payload_groups_turns_and_sub_queries() -> None:
    events = [
        {"event": "tool_call", "turn": 1, "sub_queries": 2, "cumulative_agent_turns": 1},
        {
            "event": "sub_result",
            "turn": 1,
            "sid": 1,
            "goal": "work",
            "query": "employer",
            "temporal": "current",
            "limit": 20,
            "hops": 1,
            "show_expiry": False,
            "returned": 4,
            "new": 3,
            "accumulated_total": 4,
        },
        {
            "event": "sub_result",
            "turn": 1,
            "sid": 2,
            "goal": "pets",
            "query": "dog name",
            "returned": 2,
            "new": 1,
            "accumulated_total": 4,
        },
        {"event": "tool_call", "turn": 2, "sub_queries": 1, "cumulative_agent_turns": 2},
        {
            "event": "sub_result",
            "turn": 2,
            "sid": 3,
            "goal": "trip",
            "query": "last trip",
            "returned": 1,
            "new": 1,
            "accumulated_total": 5,
        },
        {"event": "final", "turn": 3, "cumulative_agent_turns": 3, "reduce_op": "latest"},
    ]
    payload = build_retrieval_loop_payload(events, max_agent_turns=4)
    assert payload is not None
    assert payload["agent_turns"] == 3
    assert payload["max_agent_turns"] == 4
    assert payload["stopped_reason"] == "model_answered"
    assert len(payload["turns"]) == 2
    assert payload["turns"][0]["sub_queries"][0]["sid"] == 1
    assert len(payload["turns"][0]["sub_queries"]) == 2
    assert payload["turns"][1]["sub_queries"][0]["sid"] == 3


def test_build_retrieval_loop_payload_marks_turn_cap_saturation() -> None:
    events = [
        {"event": "tool_call", "turn": 1, "sub_queries": 1, "cumulative_agent_turns": 1},
        {"event": "sub_result", "turn": 1, "sid": 1, "returned": 1, "new": 1, "accumulated_total": 1},
        {"event": "final", "turn": 4, "cumulative_agent_turns": 4, "reduce_op": "none"},
    ]
    payload = build_retrieval_loop_payload(events, max_agent_turns=4)
    assert payload is not None
    assert payload["stopped_reason"] == "max_agent_turns"


def test_summarize_agent_transcript_counts_searches_and_decomposition() -> None:
    events = [
        {"event": "tool_call", "turn": 1, "sub_queries": 2},
        {"event": "sub_result", "sid": 1},
        {"event": "sub_result", "sid": 2},
        {"event": "tool_call", "turn": 2, "sub_queries": 1},
        {"event": "sub_result", "sid": 3},
        {"event": "final", "cumulative_agent_turns": 3, "reduce_op": "latest"},
    ]
    summary = summarize_agent_transcript(events)
    assert summary.searches == 3
    assert summary.agent_turns == 3
    assert summary.decomposition_turns == 1


def test_format_memory_recall_output_preview_includes_summary_and_facts() -> None:
    events = [
        {"event": "tool_call", "turn": 1, "sub_queries": 1},
        {"event": "sub_result", "sid": 1},
        {"event": "final", "cumulative_agent_turns": 2, "reduce_op": "none"},
    ]
    preview = format_memory_recall_output_preview(
        events,
        facts_preview="Budget is $50",
    )
    assert preview.startswith("searches=1 · turns=2 · Budget is $50")


def test_write_agent_retrieval_trace_creates_jsonl_sidecar(tmp_path: Path) -> None:
    events = [
        {"ts_ms": 12, "event": "tool_call", "turn": 1, "sub_queries": 1},
        {"ts_ms": 89, "event": "sub_result", "turn": 1, "sid": 1, "returned": 3, "new": 3},
        {"ts_ms": 410, "event": "final", "reduce_op": "none", "cumulative_agent_turns": 2},
    ]
    write_agent_retrieval_trace(
        tmp_path,
        run_id="memeval-abc",
        slot="q_work",
        events=events,
    )
    path = agent_trace_dir(tmp_path) / "memeval-abc__q_work.jsonl"
    assert path.exists()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in rows] == ["tool_call", "sub_result", "final"]


def test_write_agent_retrieval_trace_overwrites_on_rerun(tmp_path: Path) -> None:
    """A second write with the same (run_id, slot) replaces the snapshot — does NOT append."""
    first = [
        {"ts_ms": 10, "event": "tool_call", "turn": 1, "sub_queries": 1},
        {"ts_ms": 50, "event": "final", "reduce_op": "none", "cumulative_agent_turns": 2},
    ]
    second = [
        {"ts_ms": 8, "event": "tool_call", "turn": 1, "sub_queries": 2},
        {"ts_ms": 30, "event": "sub_result", "turn": 1, "sid": 1, "returned": 4, "new": 4},
        {"ts_ms": 60, "event": "final", "reduce_op": "latest", "cumulative_agent_turns": 2},
    ]
    write_agent_retrieval_trace(tmp_path, run_id="r", slot="q", events=first)
    write_agent_retrieval_trace(tmp_path, run_id="r", slot="q", events=second)
    path = agent_trace_dir(tmp_path) / "r__q.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 3
    assert rows[-1]["reduce_op"] == "latest"
