"""Tests for agentic retrieval trace sidecar + ledger preview (P6, P9 event shapes)."""

from __future__ import annotations

import json
from pathlib import Path

from hirocli.services.memory.agent.agent_trace import (
    agent_trace_dir,
    build_recall_ledger_substeps,
    build_retrieval_loop_payload,
    format_memory_recall_output_preview,
    format_recall_items_preview,
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


def test_build_recall_ledger_substeps_orders_turn_search_rerank_answer() -> None:
    """Transcript → per-step ledger sub-rows, all under the unified ``memory_recall/`` stem and in
    execution order: a search turn (LLM, priced) → its sub-query search (graph, no model) → that
    sub-query's DEFERRED rerank row (priced) → a failed sub-query as an errored search row → the
    exit-B answer turn (LLM). Real numbered previews in output; stats in decision detail."""
    events = [
        {
            "event": "turn",
            "turn": 1,
            "kind": "search",
            "sub_queries": 2,
            "ts_ms": 100,
            "dur_ms": 90,
            "input_tokens": 800,
            "output_tokens": 40,
        },
        {"event": "tool_call", "turn": 1, "sub_queries": 2},
        {
            "event": "sub_result",
            "turn": 1,
            "sid": 1,
            "goal": "wife",
            "query": "wife name",
            "temporal": "current",
            "limit": 20,
            "hops": 1,
            "returned": 6,
            "new": 6,
            "accumulated_total": 6,
            "ts_ms": 260,
            "dur_ms": 160,
            "new_items": [
                {"t": "Dana is Misho's wife", "s": 0.89},
                {"t": "Wife works at Cairo Uni", "s": 0.72},
            ],
            "rerank": {
                "model": "cohere:rerank-v3.5",
                "calls": 1,
                "tokens": 512,
                "elapsed_ms": 40,
                "top": [{"t": "Dana is Misho's wife", "s": 0.94}],
            },
        },
        {
            "event": "sub_result",
            "turn": 1,
            "sid": 2,
            "goal": "married",
            "query": "married to",
            "returned": 0,
            "new": 0,
            "accumulated_total": 6,
            "error": "graph timeout",
            "ts_ms": 300,
            "dur_ms": 200,
        },
        {
            "event": "answer",
            "turn": 1,
            "ts_ms": 500,
            "dur_ms": 210,
            "answer_len_chars": 21,
            "answer_preview": "Your wife is Dana.",
            "input_tokens": 1600,
            "output_tokens": 12,
        },
        {"event": "final", "turn": 1, "cumulative_agent_turns": 1},
    ]
    specs = build_recall_ledger_substeps(events, model_id="openai:gpt-5.4")
    # Order + NUMBERED names: turn1 → search1 → rerank1 → search2 (errored) → answer.
    assert [s["node"] for s in specs] == [
        "memory_recall/turn1",
        "memory_recall/search1",
        "memory_recall/rerank1",
        "memory_recall/search2",
        "memory_recall/answer",
    ]
    # The LLM turn carries model + tokens, is display-only (no_fold), and its elapsed spans the WHOLE
    # turn: LLM dur (90) + its searches' wall-clock (max sub ts 300 − turn ts 100 = 200) = 290.
    turn = specs[0]
    assert turn["usage"]["model"] == "openai:gpt-5.4"
    assert turn["decision"] == ("search", "2q")
    assert turn["no_fold"] is True
    assert turn["elapsed_ms"] == 290
    # A graph search has NO usage; output is the REAL numbered facts (w/ scores), stats in detail,
    # and its elapsed is its OWN real duration (not an inter-event delta).
    ok_search = specs[1]
    assert "usage" not in ok_search
    assert ok_search["decision"] == ("recalled", "ret6/new6/acc6")
    assert ok_search["output"] == "1. Dana is Misho's wife [0.89] · 2. Wife works at Cairo Uni [0.72]"
    assert ok_search["elapsed_ms"] == 160
    assert "no_fold" not in ok_search  # searches carry no cost; folding is irrelevant
    # The deferred rerank row is priced (its own model/tokens), folds, and shows the top fact.
    rerank = specs[2]
    assert rerank["usage"]["model"] == "cohere:rerank-v3.5"
    assert rerank["usage"]["input_tokens"] == 512
    assert rerank["decision"] == ("rerank", "1call/512tok")
    assert rerank["output"] == "1. Dana is Misho's wife [0.94]"
    assert rerank["elapsed_ms"] == 40
    assert "no_fold" not in rerank  # rerank cost DOES fold (separate from the LLM aggregate)
    # The failed sub-query becomes an errored row (its real duration preserved).
    assert specs[3]["fail"]["message"] == "graph timeout"
    assert specs[3]["elapsed_ms"] == 200
    # The exit-B answer row shows the real draft text, its real duration, and is display-only.
    answer = specs[4]
    assert answer["usage"]["input_tokens"] == 1600
    assert answer["output"] == "Your wife is Dana."
    assert answer["elapsed_ms"] == 210
    assert answer["no_fold"] is True


def test_build_recall_ledger_substeps_stop_turn_shows_answer() -> None:
    """An exit-A stop turn yields a single numbered stop turn row (real LLM duration, display-only)."""
    events = [
        {
            "event": "turn",
            "turn": 1,
            "kind": "stop",
            "sub_queries": 0,
            "ts_ms": 90,
            "dur_ms": 85,
            "input_tokens": 500,
            "content_preview": "Your wife's name is Dana.",
        },
        {"event": "final", "turn": 1, "cumulative_agent_turns": 1},
    ]
    specs = build_recall_ledger_substeps(events, model_id="openai:gpt-5.4")
    assert len(specs) == 1
    assert specs[0]["node"] == "memory_recall/turn1"
    assert specs[0]["decision"] == ("stop", "exitA")
    assert specs[0]["output"] == "Your wife's name is Dana."
    assert specs[0]["elapsed_ms"] == 85  # stop turn = its own LLM duration
    assert specs[0]["no_fold"] is True


def test_format_recall_items_preview_numbers_and_scores() -> None:
    """Numbered, score-annotated, skips empty text, honors max_items — accepts compact or full rows."""
    items = [
        {"memory": "Dana is Misho's wife", "score": 0.89},
        {"t": "", "s": 0.5},  # empty text → skipped, numbering stays gap-free
        {"t": "Married in Cairo", "s": 0.81},
        {"t": "no score item"},
    ]
    out = format_recall_items_preview(items, max_items=3)
    assert out == "1. Dana is Misho's wife [0.89] · 2. Married in Cairo [0.81] · 3. no score item"


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
