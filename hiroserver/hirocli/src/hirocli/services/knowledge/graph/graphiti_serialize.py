"""Map Graphiti graph objects → the wire DTOs the admin Graph tab consumes.

The viz contract (docs/knowledge-graph-viz-design.md §7) is engine-neutral:
``{id, name, type, aliases, chunk_ids, document_ids}`` for nodes and
``{id, source, target, rel_type, chunk_ids, document_ids}`` for edges (``source``/
``target`` are node ids so the payload drops into ``force-graph``). The Graphiti
re-map adds **temporal** fields (``fact``, ``valid_at``, ``invalid_at``) on edges.

Provenance: a Graphiti ``EntityEdge`` carries ``episodes`` — and because we ingest
with ``uuid = point_id``, those episode uuids ARE the Qdrant chunk_ids (G6). Nodes
don't carry episodes directly, so a node's ``chunk_ids`` are derived (in
:func:`build_graph_dtos`) from the union of the edges that touch it; ``document_ids``
map those chunk_ids through the episode ``source_description``. ``type`` is the first
non-base label (Graphiti tags every entity with the base ``Entity`` label plus its
ontology type)."""

from __future__ import annotations

import datetime as dt
from typing import Any

# Graphiti tags every entity with this base label in addition to its ontology type.
_BASE_LABEL = "Entity"


def _iso(value: Any) -> str | None:
    """datetime → ISO-8601 string, else None (temporal fields are nullable)."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.isoformat()
    return str(value)


def _entity_type(labels: list[str]) -> str:
    """First non-base label is the ontology type; fall back to ``Entity``."""
    for label in labels:
        if label and label != _BASE_LABEL:
            return label
    return _BASE_LABEL


def _aliases_from(node: Any) -> list[str]:
    """Aliases aren't a first-class EntityNode field; a custom ontology may stash them
    under ``attributes['aliases']``. Read them when present, else empty (no fabrication)."""
    attrs = getattr(node, "attributes", None)
    aliases = attrs.get("aliases") if isinstance(attrs, dict) else None
    return [str(a) for a in aliases if a] if isinstance(aliases, list) else []


def node_to_dto(
    node: Any,
    *,
    chunk_ids: list[str] | None = None,
    document_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Graphiti ``EntityNode`` → wire node DTO. Tolerant of missing attrs.

    Entity nodes don't carry episodes, so ``chunk_ids`` / ``document_ids`` provenance
    is derived from the edges that touch the node and passed in (see
    :func:`build_graph_dtos`); absent → empty."""
    labels = list(getattr(node, "labels", None) or [])
    return {
        "id": getattr(node, "uuid", "") or "",
        "name": getattr(node, "name", "") or "",
        "type": _entity_type(labels),
        "aliases": _aliases_from(node),
        "chunk_ids": list(chunk_ids or []),
        "document_ids": list(document_ids or []),
        "summary": getattr(node, "summary", "") or "",
    }


def edge_to_dto(edge: Any, *, document_ids: list[str] | None = None) -> dict[str, Any]:
    """Graphiti ``EntityEdge`` (a RELATES_TO fact) → wire edge DTO.

    ``rel_type`` is the relation name (``LIVES_IN``); ``chunk_ids`` are the supporting
    episode uuids (== Qdrant point_ids). The full temporal window flows through for the
    viz: ``valid_at`` (became true) · ``invalid_at`` (stopped being true) · ``expired_at``
    (when the system learned it was superseded) — the last lets the tab mark retired facts."""
    episodes = [str(e) for e in (getattr(edge, "episodes", None) or []) if e]
    return {
        "id": getattr(edge, "uuid", "") or "",
        "source": getattr(edge, "source_node_uuid", "") or "",
        "target": getattr(edge, "target_node_uuid", "") or "",
        "rel_type": getattr(edge, "name", "") or "",
        "fact": getattr(edge, "fact", "") or "",
        "chunk_ids": episodes,
        "document_ids": list(document_ids or []),
        "valid_at": _iso(getattr(edge, "valid_at", None)),
        "invalid_at": _iso(getattr(edge, "invalid_at", None)),
        "expired_at": _iso(getattr(edge, "expired_at", None)),
    }


def build_graph_dtos(
    nodes: list[Any],
    edges: list[Any],
    *,
    chunk_to_document: dict[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Assemble the whole-graph viz payload with node provenance derived from edges.

    Graphiti entity nodes don't carry episodes, so a node's ``chunk_ids`` are the union
    of the supporting chunk_ids of every edge that touches it; ``document_ids`` map those
    chunk_ids through ``chunk_to_document`` (episode uuid → ``source_description`` ==
    document_id). ``chunk_to_document`` omitted → document_ids stay empty (chunk_ids still
    populate). Returns ``{"nodes": [...], "edges": [...]}``."""
    chunk_to_document = chunk_to_document or {}

    def _docs(chunk_ids: list[str]) -> list[str]:
        out: list[str] = []
        for cid in chunk_ids:
            doc = chunk_to_document.get(cid)
            if doc and doc not in out:
                out.append(doc)
        return out

    # Per-node provenance: union the chunk_ids of every edge touching the node.
    node_chunks: dict[str, set[str]] = {}
    for edge in edges:
        eps = {str(e) for e in (getattr(edge, "episodes", None) or []) if e}
        for nid in (
            getattr(edge, "source_node_uuid", "") or "",
            getattr(edge, "target_node_uuid", "") or "",
        ):
            if nid:
                node_chunks.setdefault(nid, set()).update(eps)

    node_dtos = []
    for n in nodes:
        chunks = sorted(node_chunks.get(getattr(n, "uuid", "") or "", set()))
        node_dtos.append(node_to_dto(n, chunk_ids=chunks, document_ids=_docs(chunks)))

    edge_dtos = []
    for e in edges:
        eps = [str(x) for x in (getattr(e, "episodes", None) or []) if x]
        edge_dtos.append(edge_to_dto(e, document_ids=_docs(eps)))

    return {"nodes": node_dtos, "edges": edge_dtos}


__all__ = ["build_graph_dtos", "edge_to_dto", "node_to_dto"]
