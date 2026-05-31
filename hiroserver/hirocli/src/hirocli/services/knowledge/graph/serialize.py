"""Wire serialization for graph nodes/edges → plain dicts (the viz DTO).

Single home for the GraphNode/GraphEdge → JSON-able dict mapping so the two
consumers — the live ingest events (:mod:`ingest`) and the whole-graph export
tool (:mod:`hirocli.tools.knowledge_graph`) — emit the exact same shape. The
frontend's force-graph model expects ``source``/``target`` (not
``source_id``/``target_id``) on edges, so the rename happens here, once.
"""

from __future__ import annotations

from typing import Any

from .store import GraphEdge, GraphNode


def node_to_dto(node: GraphNode) -> dict[str, Any]:
    """Serialize a node for the viz. Provenance lists are kept so the panel can
    show ``chunk_ids``/``document_ids`` and jump back to the evidence chunk."""
    return {
        "id": node.id,
        "name": node.name,
        "type": node.type,
        "aliases": list(node.aliases),
        "chunk_ids": list(node.chunk_ids),
        "document_ids": list(node.document_ids),
    }


def edge_to_dto(edge: GraphEdge) -> dict[str, Any]:
    """Serialize an edge for the viz. ``source``/``target`` match force-graph's
    link model; ``fact`` (the relation paraphrase) rides along for tooltips."""
    return {
        "id": edge.id,
        "source": edge.source_id,
        "target": edge.target_id,
        "rel_type": edge.rel_type,
        "fact": str(edge.attrs.get("fact", "")) if edge.attrs else "",
        "chunk_ids": list(edge.chunk_ids),
        "document_ids": list(edge.document_ids),
    }


__all__ = ["edge_to_dto", "node_to_dto"]
