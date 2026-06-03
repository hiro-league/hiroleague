"""Render graphiti ``search`` tracer spans into ``graph_expand`` ledger sub-steps.

`graph_expand` (agent/graph.py) is a single Graph-Runs node today — the whole
Graphiti fact-search collapsed into one row. graphiti instruments ``search()`` with
nested ``search.*`` spans (the *only* hook, since search is ~LLM-free); the
``LedgerTracer`` buffers them into ``current_spans``. This module turns that buffer
+ the :class:`GraphitiExpansion` result into **one flattened level** of sub-steps
under the ``graph_expand`` entry (docs §12.2.2):

* graphiti spans → ``embed_query`` / ``candidate_gen`` / ``bfs_expand`` / ``rrf_fuse``
  / ``rerank`` (counts from span attributes).
* the ``rerank`` node carries the **ranked fact list** (text · valid/invalid · chunk)
  in ``rich`` mode, from the final ``SearchResults`` (spans only expose counts).
* a ``temporal_filter`` wrapper node shows kept/dropped superseded facts.

Two levels only (``spawn_child`` flattens grandchildren), matching ingest's
``episode → sub-steps`` shape. Best-effort: never raises into retrieval.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hiro_commons.log import Logger

from .ledger_tracer import SpanRecord

if TYPE_CHECKING:  # avoid a hard ledger import at module load
    from hirocli.runtime.agent_graph.ledger import LedgerEntry

    from .graphiti_search import GraphitiExpansion

log = Logger.get("SVC.KNOWLEDGE.GRAPH.RETRIEVAL_LEDGER")

# graphiti ``search.*`` span name → friendly Graph-Runs node. Several rerank
# variants (recipe-dependent) collapse to one ``rerank`` node.
_SPAN_NODE_MAP: dict[str, str] = {
    "search.embed_query_vector": "embed_query",
    "search.edge_search.execute_methods": "candidate_gen",
    "search.edge_search.expand_bfs": "bfs_expand",
    "search.edge_search.seed_rrf": "rrf_fuse",
    "search.edge_search.rerank": "rerank",
    "search.edge_search.cross_encoder_rank": "rerank",
    "search.edge_search.compute_mmr": "rerank",
    "search.edge_search.node_distance_rank": "rerank",
}
# Stable render order (sub_step follows spawn order).
_NODE_ORDER = ("embed_query", "candidate_gen", "bfs_expand", "rrf_fuse", "rerank")


def _detail(node: str, attrs: dict) -> str:
    """Human stats for a retrieval node, pulled from the span's attributes."""
    if node == "embed_query":
        dim = attrs.get("query_vector.dimension")
        return f"dim={dim}" if dim is not None else "embed query"
    if node == "candidate_gen":
        methods = attrs.get("result_set_count")
        nonempty = attrs.get("non_empty_result_sets")
        bits = []
        if methods is not None:
            bits.append(f"methods={methods}")
        if nonempty is not None:
            bits.append(f"non_empty={nonempty}")
        return " · ".join(bits) or "candidate gen"
    if node in ("rrf_fuse", "rerank"):
        cand = attrs.get("candidate_count")
        rerk = attrs.get("reranked_count")
        if cand is not None and rerk is not None:
            return f"{cand} → {rerk} kept"
        if cand is not None:
            return f"candidates={cand}"
        return node
    if node == "bfs_expand":
        return "graph expansion (k_hop>1)"
    return node


def _ranked_preview(expansion: "GraphitiExpansion", *, limit: int = 6) -> str:
    """Ranked fact list for the ``rerank`` node (rich mode) — text, no vectors."""
    lines: list[str] = []
    for i, rf in enumerate(expansion.ranked[:limit], start=1):
        when = ""
        if rf.valid_at:
            when = f" valid {rf.valid_at}"
        if rf.invalid_at:
            when += f" · invalid {rf.invalid_at}"
        mark = " ⊘" if rf.superseded else ""
        chunk = f" [chunk {rf.chunk_id[:8]}]" if rf.chunk_id else ""
        lines.append(f"{i}. {rf.fact}{when}{mark}{chunk}")
    more = f" (+{len(expansion.ranked) - limit})" if len(expansion.ranked) > limit else ""
    return " | ".join(lines) + more


def flush_graph_expand(
    entry: "LedgerEntry",
    spans: list[SpanRecord],
    expansion: "GraphitiExpansion",
    *,
    temporal: str,
    ledger_detail: str = "rich",
) -> None:
    """Spawn ``graph_expand`` sub-steps from graphiti search spans + the result.

    No-op-safe: a render hiccup must never break retrieval."""
    try:
        rich = ledger_detail != "compact"
        # Merge spans by friendly node (concurrent search methods can repeat a name);
        # keep the longest-running instance's attrs, summing elapsed.
        merged: dict[str, dict] = {}
        for span in spans:
            node = _SPAN_NODE_MAP.get(span.name)
            if not node:
                continue
            slot = merged.setdefault(node, {"elapsed_ms": 0.0, "attrs": {}})
            slot["elapsed_ms"] += span.elapsed_ms
            slot["attrs"].update(span.attributes or {})

        prefix = entry.node  # e.g. "knowledge/graph_expand"
        for node in _NODE_ORDER:
            slot = merged.get(node)
            if slot is None:
                continue
            child = entry.spawn_child(
                node=f"{prefix}/{node}",
                elapsed_ms=int(slot["elapsed_ms"]),
                captures={"decision"},
            )
            child.set_decision(node)
            preview = _detail(node, slot["attrs"])
            if node == "rerank" and rich and expansion.ranked:
                preview = f"{preview} · {_ranked_preview(expansion)}"
            child.set_output_preview(preview)

        # If no rerank span fired but we have ranked facts (rich), surface them so the
        # user still sees the returned facts.
        if rich and expansion.ranked and "rerank" not in merged:
            child = entry.spawn_child(
                node=f"{prefix}/rerank", elapsed_ms=0, captures={"decision"}
            )
            child.set_decision("rerank")
            child.set_output_preview(_ranked_preview(expansion))

        # temporal_filter wrapper — our code, not a graphiti span (docs §12.2.2).
        tf = entry.spawn_child(
            node=f"{prefix}/temporal_filter", elapsed_ms=0, captures={"decision"}
        )
        tf.set_decision("temporal_filter")
        superseded = [rf for rf in expansion.ranked if rf.superseded]
        if temporal == "current":
            # Push-down: the SearchFilters lens excluded superseded facts at the query,
            # so every returned fact is already current (design §7). The Python drop
            # below is defensive and normally removes nothing.
            extra = (
                f" · {len(superseded)} slipped past push-down, dropped" if superseded else ""
            )
            detail = (
                f"current-only applied at query (push-down) · "
                f"{expansion.facts_used} current facts{extra}"
            )
        else:
            # temporal=all: history is kept; superseded facts are returned (marked ⊘),
            # not dropped — so report them as 'shown', never as 'dropped'.
            shown = f" · {len(superseded)} superseded shown" if superseded else ""
            detail = f"{expansion.facts_used} facts · history included{shown}"
        detail += f" → chunk_ids[{len(expansion.chunk_ids)}]"
        tf.set_output_preview(detail)
    except Exception:
        log.warning("⚠️ retrieval ledger — graph_expand flush failed", exc_info=True)


__all__ = ["flush_graph_expand"]
