"""Hiro's own AI calls, counted from the graph ledger (Phase 7b).

Every priced call of the core's graphs (chat, memory, knowledge, the knowledge graph, eval, speech
and transcription in a chat turn) passes the ledger's ``LedgerSink.write_rows``; it hands each
node row here and the call is counted in AI usage under the source ``hiro``.

Which rows count: node rows only (a run row sums its nodes), not the memory agent's per-turn
children (``_no_fold``: their parent row already holds the total), and only rows with a model
(decision-only rows have none). The use comes from the node label (``knowledge/…``,
``memory_recall``, ``graphiti_ingest/…``, ``eval_…``) or, for the chat's own nodes, from the run.
A node's time is the node's whole wall time (a memory recall includes its searches).

The knowledge graph's own LLM calls that never become a ledger row (observability ``off``, or outside
an ingest episode) are counted by ``count_graph_llm_usage``, its usage hook.

Not counted (the plan's Later list): reading pictures, the memory's idle sweep, write-as-character.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from ...domain.discovered_models import DISCOVERABLE_LOCAL_PROVIDERS
from .store import HIRO_SOURCE, UsageCall, record

# The family member a chat turn is for (a person id), set by the agent manager for the turn: its
# calls (and the memory work it starts) are filed under them. Empty when the sender isn't known:
# a WhatsApp number in the family list is matched now; app devices wait for Phase 10.
usage_person: ContextVar[str] = ContextVar("usage_person", default="")


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _kind_and_use(node: str, run_id: str) -> tuple[str, str]:
    """(kind, use) of one node row."""
    if node == "tts" or node.endswith("/tts"):
        return "speech", "voice_replies"
    if node == "stt" or node.endswith("/stt"):
        return "transcription", "voice_notes"
    if node.startswith("knowledge/"):
        if node.endswith("embed_query"):
            return "embedding", "knowledge"
        if node.endswith("rerank"):
            return "rerank", "knowledge"
        return "question", "knowledge"
    if node.startswith("memory_recall"):
        return ("rerank" if "rerank" in node else "question"), "memory"
    if node.startswith(("graphiti_ingest", "memory_ingest")):
        return "question", "graph"
    if node.startswith("eval_") or run_id.startswith(("memory_eval", "knowledge_eval")):
        return "question", "eval"
    if node == "vision":
        return "question", "vision"
    if run_id.startswith("knowledge-"):
        return "question", "knowledge"
    if run_id.startswith("graphiti_ingest-"):
        return "question", "graph"
    return "question", "chat"


def usage_call_from_ledger_row(row: dict[str, Any]) -> UsageCall | None:
    """The usage of one priced ledger row, or None when the row isn't a call to count."""
    if str(row.get("row_kind") or "node") != "node" or row.get("_no_fold"):
        return None
    model = str(row.get("model") or "").strip()
    if not model:
        return None
    provider = str(row.get("provider") or "").strip()
    if ":" in model:
        # Ledger rows carry the full catalog id ("google:gemini-3.8-flash"); usage keeps the model's own
        # name, as the asks do, so one model doesn't read as two on the page.
        prefix, bare = model.split(":", 1)
        provider, model = provider or prefix, bare
    kind, use = _kind_and_use(str(row.get("node") or ""), str(row.get("run_id") or ""))
    tokens_in = _int(row.get("input_tokens")) or _int(row.get("tts_text_tokens")) or _int(row.get("stt_audio_tokens"))
    tokens_out = _int(row.get("output_tokens")) or _int(row.get("tts_audio_tokens"))
    failed = str(row.get("status") or "") == "error"
    billing = "local" if provider in DISCOVERABLE_LOCAL_PROVIDERS else "api"
    cost = _float(row.get("cost_usd"))
    return UsageCall(
        kind=kind,
        source=HIRO_SOURCE,
        use=use,
        provider=provider,
        model=model,
        billing=billing,
        person_id=usage_person.get(),
        result="failed" if failed else "ok",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        ms=_int(row.get("elapsed_ms")),
        cost=cost,
        # An API call the catalog couldn't price ("" = a price missing, "0" = a model it doesn't list).
        unpriced=int(billing == "api" and not failed and cost <= 0),
    )


def count_graph_llm_usage(workspace_path: Path, usage: Any) -> None:
    """Count one knowledge-graph LLM call (Graphiti's ``GraphitiLLMUsage``) without the ledger.

    The graph's calls reach the ledger only inside an ingest episode with observability on; every
    other call (observability ``off``, or outside an episode) is priced here and counted under ``graph``,
    so AI usage never depends on how much the graph traces.
    """
    # Lazy: the ledger package imports this module (its sink counts rows here).
    from ...domain.model_catalog import get_model_catalog
    from ...runtime.agent_graph.ledger.pricing import price_row

    row = {
        "row_kind": "node",
        "node": "graphiti_ingest/llm",
        "status": "ok",
        "model": str(getattr(usage, "model_id", "") or ""),
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "elapsed_ms": int(getattr(usage, "elapsed_ms", 0) or 0),
    }
    count_ledger_row(workspace_path, price_row(row, get_model_catalog()))


def count_ledger_row(workspace_path: Path, row: dict[str, Any]) -> None:
    """Count one priced ledger row in AI usage, off the event loop when there is one."""
    call = usage_call_from_ledger_row(row)
    if call is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        record(workspace_path, call)  # a worker thread (eval, CLI): write here
        return
    # A graph node runs on the event loop: the SQLite write goes to a thread (record never raises).
    loop.run_in_executor(None, record, workspace_path, call)
