"""Agentic retrieval loop trace sidecar + ledger preview helpers (P6).

Persists one JSONL line per agent step under ``<workspace>/logs/retrieval_trace/agent/``
and summarizes the transcript for the ``memory_recall`` ledger node's ``output_preview``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from hiro_commons.log import Logger

from hirocli.services.knowledge.graph.retrieval_trace import trace_dir

log = Logger.get("SVC.MEMORY.AGENT.TRACE")

AGENT_TRACE_SUBDIR = "agent"
_write_lock = Lock()


def agent_trace_dir(workspace_path: Path) -> Path:
    """Sidecar directory: ``<workspace>/logs/retrieval_trace/agent``."""
    return trace_dir(workspace_path) / AGENT_TRACE_SUBDIR


def _safe_segment(value: str) -> str:
    """Filesystem-safe sidecar stem segment."""
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value))
    return cleaned[:120] or "run"


@dataclass(frozen=True)
class AgentTranscriptSummary:
    searches: int
    agent_turns: int
    decomposition_turns: int


def summarize_agent_transcript(
    events: list[dict[str, Any]],
) -> AgentTranscriptSummary:
    """Derive loop stats from the retrieval-agent transcript rows (P9 event shapes)."""
    searches = 0
    agent_turns = 0
    decomposition_turns = 0

    for row in events:
        event = row.get("event")
        if event == "tool_call":
            if int(row.get("sub_queries") or 0) > 1:
                decomposition_turns += 1
        elif event == "sub_result":
            searches += 1
        elif event == "final":
            agent_turns = int(row.get("cumulative_agent_turns") or agent_turns)

    return AgentTranscriptSummary(
        searches=searches,
        agent_turns=agent_turns,
        decomposition_turns=decomposition_turns,
    )


def build_retrieval_loop_payload(
    events: list[dict[str, Any]],
    *,
    max_agent_turns: int,
) -> dict[str, Any] | None:
    """Shape the admin UI ``retrieval_loop`` block from an agent transcript (P8/P9).

    Each turn groups its sub-query results into ``sub_queries``. Returns ``None`` when the
    transcript has no searchable steps (legacy / skipped agent).
    """
    if not events:
        return None

    turns_by_no: dict[int, dict[str, Any]] = {}
    current_turn = 0
    agent_turns = 0
    stopped_reason = "model_answered"

    for row in events:
        event = row.get("event")
        if event == "tool_call":
            current_turn = int(row.get("turn") or current_turn or 1)
            turns_by_no.setdefault(current_turn, {"turn": current_turn, "sub_queries": []})
        elif event == "sub_result":
            turn_no = int(row.get("turn") or current_turn or 1)
            turn_row = turns_by_no.setdefault(turn_no, {"turn": turn_no, "sub_queries": []})
            turn_row["sub_queries"].append(
                {
                    "sid": int(row.get("sid") or 0),
                    "goal": str(row.get("goal") or ""),
                    "query": str(row.get("query") or ""),
                    "temporal": row.get("temporal") or "current",
                    "limit": int(row.get("limit") or 20),
                    "hops": int(row.get("hops") or 1),
                    "show_expiry": bool(row.get("show_expiry")),
                    "returned": int(row.get("returned") or 0),
                    "new": int(row.get("new") or 0),
                    "accumulated_total": int(row.get("accumulated_total") or 0),
                }
            )
        elif event == "final":
            agent_turns = int(row.get("cumulative_agent_turns") or agent_turns)
            stopped_reason = (
                "max_agent_turns" if agent_turns >= max_agent_turns else "model_answered"
            )

    if not turns_by_no:
        return None

    turns = [turns_by_no[key] for key in sorted(turns_by_no)]
    return {
        "turns": turns,
        "agent_turns": agent_turns,
        "max_agent_turns": max_agent_turns,
        "stopped_reason": stopped_reason,
    }


def format_memory_recall_output_preview(
    events: list[dict[str, Any]],
    *,
    facts_preview: str,
) -> str:
    """Ledger preview: ``searches=N · turns=M · <facts>``."""
    summary = summarize_agent_transcript(events)
    head = f"searches={summary.searches} · turns={summary.agent_turns}"
    facts = (facts_preview or "").strip()
    if not facts or facts == "(nothing recalled)":
        return head
    return f"{head} · {facts}"


def write_agent_retrieval_trace(
    workspace_path: Path,
    *,
    run_id: str,
    slot: str,
    events: list[dict[str, Any]],
) -> None:
    """Write one JSONL line per agent step (best-effort — never raises).

    ``slot`` is the surface-neutral sub-key of the run (Phase 0 G3): eval passes the question id,
    chat passes the recall node's ``step_index``. The events list is the full transcript for one
    ``slot``, so the sidecar is opened in write mode (a re-run with the same ``run_id``/``slot``
    overwrites the previous snapshot instead of appending duplicate rows).
    """
    if not events:
        return
    try:
        directory = agent_trace_dir(workspace_path)
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{_safe_segment(run_id)}__{_safe_segment(slot)}"
        path = directory / f"{stem}.jsonl"
        lines = [json.dumps(row, ensure_ascii=False, default=str) for row in events]
        with _write_lock:
            with path.open("w", encoding="utf-8") as fh:
                for line in lines:
                    fh.write(line + "\n")
    except Exception:
        log.warning(
            "⚠️ agent retrieval trace — sidecar write failed · run_id=%s · slot=%s",
            run_id,
            slot,
            exc_info=True,
        )


__all__ = [
    "AgentTranscriptSummary",
    "agent_trace_dir",
    "build_retrieval_loop_payload",
    "format_memory_recall_output_preview",
    "summarize_agent_transcript",
    "write_agent_retrieval_trace",
]
