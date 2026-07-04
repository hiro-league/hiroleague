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


_USAGE_KEYS = ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens")


def _step_usage(model_id: str, row: dict[str, Any]) -> dict[str, Any]:
    """The ``record_child(usage=…)`` payload for one LLM turn/answer transcript row.

    Carries the model id (so the sub-row prices) + whichever per-turn token counts the event
    recorded. The provider prefix mirrors ``_write_recall_usage`` — the pricing catalog is keyed by
    the prefixed ``provider:model`` id."""
    usage: dict[str, Any] = {
        "provider": model_id.partition(":")[0] if ":" in model_id else "",
        "model": model_id,
    }
    for key in _USAGE_KEYS:
        value = row.get(key)
        if value is not None:
            usage[key] = int(value)
    return usage


_RECALL_TEXT_KEYS = ("memory", "fact", "text", "summary", "content", "name")


def compact_recall_item(item: dict[str, Any]) -> dict[str, Any]:
    """``{"t": text, "s": score|None}`` — the minimal shape the numbered preview renders from.

    Accepts a raw recall hit OR a serialized accumulator item (both carry a text field + score), so
    the search / rerank / parent previews all normalize through one path."""
    text = ""
    for key in _RECALL_TEXT_KEYS:
        val = str(item.get(key) or "").strip()
        if val:
            text = val
            break
    score = item.get("score")
    return {"t": text, "s": float(score) if isinstance(score, (int, float)) else None}


def format_recall_items_preview(
    items: list[dict[str, Any]], *, max_items: int = 3, max_chars: int = 64
) -> str:
    """Numbered, score-annotated one-liner: ``1. <text> [0.89] · 2. <text> [0.72]``.

    ``items`` may be compact ``{t,s}`` dicts OR full recall dicts (normalized via
    :func:`compact_recall_item`). The score bracket is omitted when absent; empty-text items are
    skipped so the numbering stays gap-free. This is the *real* recalled content the output_preview
    shows (the stats move to ``decision_detail``)."""
    parts: list[str] = []
    for item in items:
        compact = item if "t" in item else compact_recall_item(item)
        text = str(compact.get("t") or "").strip()
        if not text:
            continue
        if len(text) > max_chars:
            text = text[: max_chars - 1] + "…"
        idx = len(parts) + 1
        score = compact.get("s")
        if isinstance(score, (int, float)):
            parts.append(f"{idx}. {text} [{score:.2f}]")
        else:
            parts.append(f"{idx}. {text}")
        if len(parts) >= max_items:
            break
    return " · ".join(parts)


def build_recall_ledger_substeps(
    events: list[dict[str, Any]],
    *,
    model_id: str,
) -> list[dict[str, Any]]:
    """Map a retrieval-loop transcript into per-step ledger sub-rows (``record_child`` kwargs).

    Turns the loop's internals into Graph-Runs sub-nodes under the ``memory_recall`` step — all under
    the SAME ``memory_recall/`` stem as the parent + the rerank rows (so they group and indent
    together), in true execution order (``turn`` → its ``search`` rows, each immediately followed by
    its deferred ``rerank`` row → the next turn):

    - ``memory_recall/turn`` — one per LLM decision turn (``turn`` event): model + per-turn tokens/
      cost; decision ``search/Nq`` (decomposed into N sub-queries) or ``stop`` (exit A). Output = the
      dispatched sub-queries / the stop-turn answer.
    - ``memory_recall/search`` — one per sub-query (``sub_result`` event): NO model/cost (a graph-DB
      search). Output = the real NEW facts recalled (numbered, scored); detail = ret/new/acc counts.
      A failed sub-query / whole-tool error (``tool_error``) becomes an errored search row.
    - ``memory_recall/rerank`` — the deferred cross-encoder roll-up for a sub-query (``rerank`` block
      on the ``sub_result``): model + processed tokens/cost. Output = the top reranked facts (scored).
    - ``memory_recall/answer`` — the optional exit-B compose call (``answer`` event): model + tokens.

    ``decision_detail`` carries the STATS (slug-safe ``ret6/new6/acc8`` etc.); ``output_preview``
    carries the REAL content. Pure over the transcript (the loop stays ledger-free); the node calls
    ``record_child(**spec)`` per spec. ``elapsed_ms`` is the inter-event delta from ``ts_ms``."""
    subs_by_turn: dict[int, list[dict[str, Any]]] = {}
    for row in events:
        if row.get("event") == "sub_result":
            subs_by_turn.setdefault(int(row.get("turn") or 0), []).append(row)

    specs: list[dict[str, Any]] = []
    for row in events:
        event = row.get("event")
        if event not in ("turn", "sub_result", "tool_error", "answer"):
            continue

        if event == "turn":
            turn_no = int(row.get("turn") or 0)
            usage = _step_usage(model_id, row)
            content = str(row.get("content_preview") or "").strip()
            turn_dur = int(row.get("dur_ms") or 0)
            if row.get("kind") == "stop":
                specs.append(
                    {
                        # Numbered so a turn/search/rerank is identifiable at a glance (turn1, turn2…).
                        "node": f"memory_recall/turn{turn_no}",
                        "elapsed_ms": turn_dur,
                        "input": f"turn {turn_no}: decide",
                        "output": content or "stopped searching — has answer",
                        "decision": ("stop", "exitA"),
                        "usage": usage,
                        "captures": ("usage", "decision"),
                        # LLM cost lives on the parent memory_recall aggregate too (like eval); mark
                        # the per-turn row display-only so the run total isn't double-counted.
                        "no_fold": True,
                    }
                )
            else:
                subs = subs_by_turn.get(turn_no, [])
                n_sub = int(row.get("sub_queries") or 0)
                dispatched = " · ".join(
                    f"{i}. {(str(s.get('goal') or s.get('query') or '')).strip()}"
                    for i, s in enumerate(subs, 1)
                    if str(s.get("goal") or s.get("query") or "").strip()
                )
                # A search turn's displayed elapsed spans the WHOLE turn: its own LLM decision call
                # PLUS the searches it launched (which run after the decision, concurrently). Otherwise
                # the turn read shorter than a search "inside" it. = LLM dur + (last search end − LLM
                # end). Falls back to the LLM dur when the turn launched no searches.
                turn_ts = int(row.get("ts_ms") or 0)
                max_sub_ts = max((int(s.get("ts_ms") or 0) for s in subs), default=turn_ts)
                whole_turn_ms = turn_dur + max(0, max_sub_ts - turn_ts)
                specs.append(
                    {
                        "node": f"memory_recall/turn{turn_no}",
                        "elapsed_ms": whole_turn_ms,
                        "input": f"turn {turn_no}: decompose",
                        "output": dispatched or f"{n_sub} sub-quer{'y' if n_sub == 1 else 'ies'}",
                        "decision": ("search", f"{n_sub}q"),
                        "usage": usage,
                        "captures": ("usage", "decision"),
                        "no_fold": True,
                    }
                )
        elif event == "sub_result":
            sid = row.get("sid")
            goal = str(row.get("goal") or "").strip()
            head = f"S{sid} · {goal}" if goal else f"S{sid}"
            query = str(row.get("query") or "").strip()
            inp = (
                f"{head}: {query} "
                f"[{row.get('temporal') or 'current'} · lim {row.get('limit')} · hop {row.get('hops')}]"
            )
            search_dur = int(row.get("dur_ms") or 0)
            error = str(row.get("error") or "").strip()
            if error:
                specs.append(
                    {
                        "node": f"memory_recall/search{sid}",
                        "elapsed_ms": search_dur,
                        "input": inp,
                        "fail": {
                            "code": "search_error",
                            "message": error,
                            "decision": "search_error",
                        },
                    }
                )
            else:
                returned = int(row.get("returned") or 0)
                new = int(row.get("new") or 0)
                acc = int(row.get("accumulated_total") or 0)
                preview = format_recall_items_preview(row.get("new_items") or [])
                specs.append(
                    {
                        "node": f"memory_recall/search{sid}",
                        "elapsed_ms": search_dur,
                        "input": inp,
                        "output": preview or "(no new items)",
                        "decision": ("recalled", f"ret{returned}/new{new}/acc{acc}"),
                    }
                )
            # The deferred cross-encoder roll-up for THIS sub-query — emitted right after its search
            # row so it reads in execution order (see memory.search ``rerank_sink``). Absent for
            # RRF/MMR / local rerankers (no priced cross-encoder ran). It DOES fold (cheap cloud cost
            # itemized in the run total, separate from the LLM aggregate on the parent).
            rerank = row.get("rerank")
            if isinstance(rerank, dict) and rerank.get("model"):
                model = str(rerank.get("model") or "")
                specs.append(
                    {
                        "node": f"memory_recall/rerank{sid}",
                        "elapsed_ms": int(rerank.get("elapsed_ms") or 0),
                        "input": f"{head}: cross-encoder rerank",
                        "output": format_recall_items_preview(rerank.get("top") or [])
                        or "(reranked)",
                        "decision": (
                            "rerank",
                            f"{int(rerank.get('calls') or 0)}call/{int(rerank.get('tokens') or 0)}tok",
                        ),
                        "usage": {
                            "provider": model.partition(":")[0] if ":" in model else "",
                            "model": model,
                            "input_tokens": int(rerank.get("tokens") or 0),
                        },
                        "captures": ("usage", "decision"),
                    }
                )
        elif event == "tool_error":
            specs.append(
                {
                    "node": "memory_recall/search",
                    "elapsed_ms": 0,
                    "input": "tool call",
                    "fail": {
                        "code": "tool_error",
                        "message": str(row.get("error") or "").strip(),
                        "decision": "tool_error",
                    },
                }
            )
        elif event == "answer":
            answer = str(row.get("answer_preview") or "").strip()
            specs.append(
                {
                    "node": "memory_recall/answer",
                    "elapsed_ms": int(row.get("dur_ms") or 0),
                    "input": "compose final answer (budget exhausted)",
                    "output": answer or f"draft · {int(row.get('answer_len_chars') or 0)} chars",
                    "decision": ("answered", "exitB"),
                    "usage": _step_usage(model_id, row),
                    "captures": ("usage", "decision"),
                    "no_fold": True,
                }
            )
    return specs


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


def write_agent_recall_result(
    workspace_path: Path,
    *,
    run_id: str,
    slot: str,
    recalled: list[dict[str, Any]],
    answer: str,
) -> None:
    """Persist the recalled rows + draft answer beside the transcript (best-effort — never raises).

    A CHAT ``memory_recall`` node has no ``eval_results.db`` row, so the Graph-Runs detail dialog has
    nowhere to read the recalled facts/entities/episodes or the draft answer from. This companion
    (``{run}__{slot}.result.json``) mirrors what eval stores in ``row_json`` so that dialog can render
    the SAME Overview + Facts/Entities/Episodes tables (with counts) a memory-eval row shows.
    """
    try:
        directory = agent_trace_dir(workspace_path)
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{_safe_segment(run_id)}__{_safe_segment(slot)}"
        path = directory / f"{stem}.result.json"
        payload = {"recalled": recalled, "answer": answer or ""}
        with _write_lock:
            path.write_text(
                json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8"
            )
    except Exception:
        log.warning(
            "⚠️ agent recall result — sidecar write failed · run_id=%s · slot=%s",
            run_id,
            slot,
            exc_info=True,
        )


def read_agent_recall_result(workspace_path: Path, run_id: str) -> dict[str, Any]:
    """Read the recalled-rows + draft-answer companion for ``run_id`` ({} on miss/error).

    Globs ``{run}__*.result.json`` and returns the first slot's ``{recalled, answer}``. Companion to
    :func:`read_agent_retrieval_trace` (the transcript is ``.jsonl``, this is ``.result.json``)."""
    try:
        directory = agent_trace_dir(workspace_path)
        matches = sorted(directory.glob(f"{_safe_segment(run_id)}__*.result.json"))
        if not matches:
            return {}
        data = json.loads(matches[0].read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        log.warning(
            "⚠️ agent recall result — read failed · run_id=%s", run_id, exc_info=True
        )
        return {}


def read_agent_retrieval_trace(workspace_path: Path, run_id: str) -> list[dict[str, Any]]:
    """Read the agent-loop transcript sidecar for ``run_id`` (best-effort — [] on miss/error).

    Globs ``{run}__*.jsonl`` and returns the first slot's events. A chat turn has one recall slot
    (keyed by ``step_index``); eval keys by question id. Backs the Graph-Runs trajectory dialog."""
    try:
        directory = agent_trace_dir(workspace_path)
        matches = sorted(directory.glob(f"{_safe_segment(run_id)}__*.jsonl"))
        if not matches:
            return []
        events: list[dict[str, Any]] = []
        for raw in matches[0].read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events
    except Exception:
        log.warning(
            "⚠️ agent retrieval trace — read failed · run_id=%s", run_id, exc_info=True
        )
        return []


__all__ = [
    "AgentTranscriptSummary",
    "agent_trace_dir",
    "build_recall_ledger_substeps",
    "build_retrieval_loop_payload",
    "compact_recall_item",
    "format_recall_items_preview",
    "format_memory_recall_output_preview",
    "read_agent_recall_result",
    "read_agent_retrieval_trace",
    "summarize_agent_transcript",
    "write_agent_recall_result",
    "write_agent_retrieval_trace",
]
