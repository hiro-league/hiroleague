"""What the graph viewer reads: the whole-graph snapshot, the group list, a group's episodes, and the text
behind a node's chunks (for groups that live only in Kuzu). Read-only; each read takes the owner's query
timeout (``graph.query_timeout_s`` in the core)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .graphiti_serialize import build_graph_dtos
from .graphiti_service import (
    graphiti_db_path,
    read_episode_chunks,
    read_graph_episodes,
    read_graph_group_ids,
    read_graph_snapshot,
)
from .group_scope import classify_group, group_label, is_kuzu_only_chunk_group_id

# Safety caps for the whole-graph export (the Graph tab's load path). The graph is
# small by design; these only exist so a runaway graph can't produce an unbounded
# payload. The response flags ``truncated`` when a cap is hit.
DEFAULT_NODE_LIMIT = 5000
DEFAULT_EDGE_LIMIT = 10000


async def graph_snapshot_payload(
    workspace_path: Path,
    *,
    node_limit: int | None = None,
    edge_limit: int | None = None,
    group_ids: list[str] | None = None,
    query_timeout_s: int = 60,
) -> dict[str, Any]:
    """Whole-graph export for the Graph tab (Graphiti → wire DTO).

    Read-only: reads every entity node + RELATES_TO fact from Kuzu (no models),
    maps to the viz DTO (entities + relations + temporal windows). ``group_ids`` selects the
    partition — default knowledge group, or a ``mem_{user}_{character}`` conversation-memory
    group. Returns an empty graph when none is built yet — never an ingest side effect.
    ``truncated`` flags a safety-cap hit.
    """
    node_limit = node_limit or DEFAULT_NODE_LIMIT
    edge_limit = edge_limit or DEFAULT_EDGE_LIMIT
    nodes, edges, chunk_to_document, episode_mentions = await read_graph_snapshot(
        graphiti_db_path(workspace_path),
        node_limit=node_limit,
        edge_limit=edge_limit,
        group_ids=group_ids,
        query_timeout_s=query_timeout_s,
    )
    truncated = len(nodes) >= node_limit or len(edges) >= edge_limit
    dtos = build_graph_dtos(
        nodes, edges, chunk_to_document=chunk_to_document, episode_mentions=episode_mentions
    )
    return {
        "nodes": dtos["nodes"],
        "edges": dtos["edges"],
        "truncated": truncated,
        "counts": {"nodes": len(nodes), "edges": len(edges)},
    }


def label_graph_group(group_id: str) -> dict[str, str]:
    """One Graph-tab selector entry: ``{id, label, kind}``. Both the **logical label** and the
    **kind** come from the firm group-ID policy (group_scope) so naming is defined in one place
    (docs/graph-group-policy-design.md §4) — knowledge/memory/eval render as logical names, not
    raw ids; legacy/unknown ids fall back to the raw id so they stay selectable/removable."""
    return {"id": group_id, "label": group_label(group_id), "kind": classify_group(group_id)}


async def graph_groups_payload(workspace_path: Path, *, query_timeout_s: int = 60) -> dict[str, Any]:
    """List the graph's partitions for the Graph tab's group selector.

    Returns ``{"default_group_id", "groups": [{id, label, kind}]}`` — "Knowledge" first,
    then conversation-memory groups, then any others. Empty when no graph is built yet.
    """
    group_ids, default_gid = await read_graph_group_ids(
        graphiti_db_path(workspace_path), query_timeout_s=query_timeout_s
    )
    labeled = [label_graph_group(g) for g in group_ids]
    # Stable, friendly order: knowledge first, then memory, then eval, then other — each
    # alphabetical.
    kind_rank = {"knowledge": 0, "memory": 1, "eval": 2, "other": 3}
    labeled.sort(key=lambda g: (kind_rank.get(g["kind"], 9), g["label"].lower()))
    return {"default_group_id": default_gid, "groups": labeled}


async def graph_episodes_payload(
    workspace_path: Path, group_id: str, *, limit: int = 2000, query_timeout_s: int = 60
) -> dict[str, Any]:
    """List a graph partition's episodes for the Graph tab's episode filter.

    Returns ``{"episodes": [{id, snippet, preview, valid_at, document_id}]}`` ordered by chunk_id
    (== corpus episode order). Each ``id`` is a chunk_id the client matches against node/edge
    ``chunk_ids`` to filter the graph to those episodes. Empty when the group has no episodes
    / no graph built yet.
    """
    episodes = await read_graph_episodes(
        graphiti_db_path(workspace_path),
        group_id,
        limit=limit,
        query_timeout_s=query_timeout_s,
    )
    return {"episodes": episodes}


async def kuzu_chunk_details(
    workspace_path: Path, point_ids: list[str], *, query_timeout_s: int = 60
) -> list[dict[str, Any]]:
    """The text behind chunk ids whose episode lives only in Kuzu (conversation and eval memory).

    Knowledge chunks keep their text elsewhere (the core's Qdrant), so they are left out here; an
    owner with a knowledge base hands the router its own lookup for those.
    """
    ids = [str(p) for p in (point_ids or []) if p]
    if not ids:
        return []
    episode_by_id = await read_episode_chunks(
        graphiti_db_path(workspace_path), ids, query_timeout_s=query_timeout_s
    )
    details: list[dict[str, Any]] = []
    for pid in ids:
        episode = episode_by_id.get(pid, {})
        group_id = str(episode.get("group_id", "") or "")
        text = str(episode.get("text", "") or "")
        if not is_kuzu_only_chunk_group_id(group_id) or not text:
            continue
        details.append(
            {
                "id": pid,
                "text": text,
                # Conversation memory has no source document; surface the thread id (set as
                # ``source_description`` at ingest: "conv:{run_id}") so the panel can still group
                # + label memory chunks coherently.
                "document_id": episode.get("source_description") or group_id,
                "document_title": "Conversation",
                "ord": None,
                "heading_path": None,
                "valid_at": episode.get("valid_at"),
            }
        )
    return details
