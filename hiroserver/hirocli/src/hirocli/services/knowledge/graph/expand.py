"""L3 graph expansion — query entities → relevant Qdrant chunk_ids.

Given a list of entity mentions extracted from the user's query (by the
``QueryRewrite`` step), this module:

  1. Resolves each mention to a graph node via **name-or-alias** exact match
     (the same deterministic path the ingest resolver uses, but read-only).
  2. Expands by **k hops** to gather connected nodes (and the edges between them).
  3. Returns the **union of chunk_ids** stored as provenance on every touched
     node and edge — that's the focused candidate set Qdrant hybrid+rerank runs
     over when the ``use_graph`` toggle is on.

This is engine-agnostic on the LLM side (no model needed) — pure graph reads.
Soft-fallback policy lives in the **caller**: when this returns an empty set,
the caller should fall through to flat search (don't apply a chunk_id filter).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from hiro_commons.log import Logger

from .ladybug_adapter import LadybugGraphStore
from .store import normalize_name

log = Logger.get("SVC.KNOWLEDGE.GRAPH.EXPAND")


@dataclass(frozen=True)
class GraphExpansion:
    """Result of expanding query entities through the graph.

    Surfaced to the ledger so each Ask reports how the graph helped — empty
    ``chunk_ids`` is the signal that the graph couldn't anchor this query and
    the caller fell back to unfiltered search."""

    chunk_ids: tuple[str, ...]
    nodes_touched: int
    entities_resolved: int  # how many of the input mentions matched something
    entities_requested: int
    # Human-readable detail for the ledger (not just counts): which mentions matched, and the
    # names of the touched nodes (seed + k-hop neighbors). Defaulted so empty-result paths stay terse.
    resolved_entities: tuple[str, ...] = ()
    node_names: tuple[str, ...] = ()


def _normalized_entities(entities: Iterable[str]) -> list[str]:
    """Dedupe + drop empties — defensive, because the LLM-extracted entities[]
    field can include the same name twice or stray whitespace."""
    seen: dict[str, None] = {}
    for raw in entities or ():
        text = (raw or "").strip()
        if not text:
            continue
        # Use the raw text as the dedup key (case-preserving) — normalization
        # for matching happens inside the store call.
        if text not in seen:
            seen[text] = None
    return list(seen)


def _expand_sync(db_path: Path, entities: list[str], k: int) -> GraphExpansion:
    """Sync core — runs inside asyncio.to_thread so Ladybug calls don't block the loop."""
    chunk_ids: set[str] = set()
    # id -> name so the ledger can report WHICH nodes were touched, not just a count.
    nodes_touched: dict[str, str] = {}
    resolved_entities: list[str] = []

    store = LadybugGraphStore.open(db_path)
    try:
        for raw_name in entities:
            normalized = normalize_name(raw_name)
            if not normalized:
                continue
            hits = store.find_by_name_exact(normalized)
            if not hits:
                continue
            resolved_entities.append(raw_name)
            for hit in hits:
                if hit.id in nodes_touched:
                    continue
                nodes_touched[hit.id] = hit.name
                chunk_ids.update(hit.chunk_ids)
                # k-hop neighbors + their chunk_ids
                if k >= 1:
                    for neighbor in store.neighbors(hit.id, k=k):
                        if neighbor.id in nodes_touched:
                            continue
                        nodes_touched[neighbor.id] = neighbor.name
                        chunk_ids.update(neighbor.chunk_ids)
                    # Edges *incident* to the seed carry provenance too — the
                    # chunk that asserted the relation often holds the answer.
                    for edge in store.edges(hit.id, direction="both"):
                        chunk_ids.update(edge.chunk_ids)
    finally:
        store.close()

    return GraphExpansion(
        chunk_ids=tuple(sorted(chunk_ids)),  # sorted → deterministic filter keys
        nodes_touched=len(nodes_touched),
        entities_resolved=len(resolved_entities),
        entities_requested=len(entities),
        resolved_entities=tuple(resolved_entities),
        node_names=tuple(name for name in nodes_touched.values() if name),
    )


async def expand_entities_to_chunk_ids(
    db_path: Path,
    entities: Iterable[str],
    *,
    k: int = 1,
) -> GraphExpansion:
    """Resolve entity mentions → k-hop chunk_ids. Empty result == no anchor found.

    - ``db_path`` is the workspace's Ladybug file. If the file doesn't exist yet
      (no ingest has run), returns an empty expansion without trying to open it.
    - ``entities`` is the LLM-extracted list from ``QueryRewrite``.
    - ``k=1`` is the prototype default. k=0 == only the seed node (rare; mostly
      useful for "exactly this entity, no neighbors" queries).
    """
    cleaned = _normalized_entities(entities)
    if not cleaned:
        return GraphExpansion(chunk_ids=(), nodes_touched=0, entities_resolved=0, entities_requested=0)
    if not db_path.exists():
        # Graph never ingested for this workspace — silent no-op (caller falls
        # back to flat search). INFO not warning: this is the expected state
        # for a workspace that hasn't opted into the L3 prototype yet.
        log.info("⬇️ graph.expand — no graph DB · skipping · path=%s", db_path)
        return GraphExpansion(chunk_ids=(), nodes_touched=0, entities_resolved=0, entities_requested=len(cleaned))

    try:
        expansion = await asyncio.to_thread(_expand_sync, db_path, cleaned, k)
    except Exception:
        # External-engine call: log + raise. The agent graph treats this as the
        # node failing — graph_chunk_ids stays empty, caller falls back to flat.
        log.exception("❌ graph.expand — Ladybug read failed · path=%s", db_path)
        raise

    log.info(
        "⬇️ graph.expand — entities=%d/%d nodes=%d chunks=%d",
        expansion.entities_resolved,
        expansion.entities_requested,
        expansion.nodes_touched,
        len(expansion.chunk_ids),
    )
    return expansion


__all__ = ["GraphExpansion", "expand_entities_to_chunk_ids"]
