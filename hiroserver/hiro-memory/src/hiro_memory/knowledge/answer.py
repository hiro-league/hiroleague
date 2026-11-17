"""One standalone answer of the knowledge graph: its initial state, its run (in a ledger run of its own, or nested
under the caller's), and its result.

The owner builds the graph (``agent.KnowledgeAgentGraph(sinks).build(config)``) and resolves its own defaults (top_k
and min_score from its settings); this runs it the way the core's ``KnowledgeService.answer`` always has, so the core
and EvalHiro answer the same way.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from hiro_commons.log import Logger

from hiro_memory.knowledge.ledger_runner import (
    finalize_standalone_run,
    knowledge_answer_ledger,
    ledger_identity_from_parent,
)
from hiro_memory.knowledge.models import KnowledgeAnswerResult
from hiro_memory.ledger import current_run

log = Logger.get("SVC.KNOWLEDGE")


def answer_state(
    query: str,
    *,
    top_k: int,
    min_score: float,
    filters: dict[str, Any] | None = None,
    explain: bool = False,
    rewrite: bool = False,
    graph_mode: str = "off",
    graph_temporal: str | None = None,
) -> dict[str, Any]:
    """The graph's initial state for one answer. A run already open (a chat turn) lends its identity to the state."""
    state: dict[str, Any] = {
        "query": query,
        "filters": filters or {},
        "top_k": top_k,
        "min_score": min_score,
        "explain": explain,
        "rewrite": rewrite,
        "graph_mode": graph_mode,
        # Per-query temporal override (G9/§7): "current" | "all". Empty/None →
        # graph_expand falls back to the admin pref ``temporal_default``.
        "graph_temporal": graph_temporal or "",
    }
    parent = current_run.get()
    if parent is not None:
        state.update(ledger_identity_from_parent(parent))
    return state


@dataclass(frozen=True)
class AnswerRun:
    """The graph's final state, and the ledger run it ran in."""

    state: dict[str, Any]
    run_id: str | None


async def run_answer(graph: Any, *, sink: Any, query: str, initial_state: dict[str, Any]) -> AnswerRun:
    """Run the answer graph in its ledger run (nested under an open run, else standalone with its aggregate row).
    A failure is logged and raised; the aggregate row records it either way."""
    terminal_status = "completed"
    terminal_error = ""
    state: dict[str, Any] = {}
    ledger_run_id: str | None = None
    async with knowledge_answer_ledger(sink=sink, query=query) as ledger_run:
        ledger_run_id = ledger_run.run_id
        try:
            state = await graph.ainvoke(
                initial_state,
                config=ledger_run.runnable_config,
            )
        except asyncio.CancelledError:
            terminal_status = "cancelled"
            terminal_error = "cancelled"
            raise
        except Exception as exc:
            terminal_status = "failed"
            terminal_error = str(exc)[:80]
            log.error(
                "❌ knowledge answer graph failed",
                error=str(exc),
                exc_info=True,
            )
            raise
        finally:
            if ledger_run.accumulator is not None:
                finalize_standalone_run(
                    ledger_run.accumulator,
                    query=query,
                    answer=str(state.get("answer") or ""),
                    no_results=bool(state.get("no_results")),
                    status=terminal_status,
                    error_code=terminal_error,
                )
    return AnswerRun(state=state, run_id=ledger_run_id)


def answer_result(query: str, run: AnswerRun) -> KnowledgeAnswerResult:
    """The answer as callers read it, from the graph's final state."""
    state = run.state
    return KnowledgeAnswerResult(
        query=query,
        answer=str(state.get("answer") or ""),
        sources=list(state.get("sources") or []),
        elapsed_ms=int(state.get("elapsed_ms") or 0),
        model_id=state.get("model_id"),
        usage=dict(state.get("usage") or {}),
        no_results=bool(state.get("no_results")),
        run_id=run.run_id,
        rewritten_query=state.get("rewritten_query"),
        keywords=list(state.get("rewrite_keywords") or []),
    )


__all__ = ["AnswerRun", "answer_result", "answer_state", "run_answer"]
