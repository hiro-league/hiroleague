"""Attach the priced rerank roll-up to the ``graph_expand`` / ``memory_recall`` ledger row.

The graphiti fact-search is one Graph-Runs node. Its only **billable** sub-operation is the
cross-encoder rerank (cloud Cohere/Voyage); the embedding / candidate / bfs / rrf stages are
local and free. So at the ``ledger`` observability tier we attach a SINGLE priced ``rerank``
roll-up child carrying the model + processed tokens — its cost folds into the ``@run`` aggregate —
and nothing else. The deep per-stage search breakdown (candidate legs / hop / rank / temporal)
lives ONLY in the ``trace``-tier JSONL sidecar (docs §12.2), not as ledger sub-rows.

RRF/MMR recipes and local-only rerankers add no child (no catalogued cost). Best-effort: a render
hiccup must never break retrieval.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hiro_commons.log import Logger

from .ledger_tracer import RerankUsage

if TYPE_CHECKING:  # avoid a hard ledger import at module load
    from hirocli.runtime.agent_graph.ledger import LedgerEntry

    from .graphiti_search import GraphitiExpansion

log = Logger.get("SVC.KNOWLEDGE.GRAPH.RETRIEVAL_LEDGER")


def _rerank_priced(usage: "RerankUsage | None") -> bool:
    """True only when a catalogued cross-encoder actually ran (model id + ≥1 call).

    RRF/MMR recipes and local-only rerankers leave this False, so no priced child is spawned."""
    return usage is not None and bool(usage.model_id) and usage.calls > 0


def flush_graph_expand(
    entry: "LedgerEntry",
    expansion: "GraphitiExpansion",
    *,
    rerank_usage: "RerankUsage | None" = None,
) -> None:
    """Attach the rerank roll-up to the fact-search ledger row (``entry``).

    Spawns ONE priced ``rerank`` child when a catalogued cross-encoder ran (cost folds into the
    run aggregate); nothing otherwise. The parent row already carries the facts/chunks summary
    (set by its node); the per-stage search breakdown is the ``trace`` sidecar's job."""
    try:
        if not _rerank_priced(rerank_usage):
            return
        usage = rerank_usage  # narrowed by _rerank_priced
        provider = usage.model_id.partition(":")[0] if ":" in usage.model_id else ""
        child = entry.spawn_child(
            node=f"{entry.node}/rerank",
            elapsed_ms=int(usage.elapsed_ms),
            captures={"usage", "decision"},
        )
        child.set_decision("rerank", usage.model_id)
        # Prefixed catalog id + processed tokens → ``_with_cost`` prices it (Voyage per-token /
        # Cohere per-search-unit); a local reranker id misses the catalog and prices as $0.
        child.add_usage(
            provider=provider,
            model=usage.model_id,
            input_tokens=usage.processed_tokens,
        )
        child.set_output_preview(
            f"reranked {len(expansion.ranked)} facts · {usage.calls} call(s) · "
            f"{usage.processed_tokens} tok"
        )
    except Exception:
        log.warning("⚠️ retrieval ledger — rerank roll-up flush failed", exc_info=True)


__all__ = ["flush_graph_expand"]
