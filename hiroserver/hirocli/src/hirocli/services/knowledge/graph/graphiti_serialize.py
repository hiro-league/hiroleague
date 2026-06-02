"""Map Graphiti graph objects → the wire DTOs the admin Graph tab consumes.

The viz contract (docs/knowledge-graph-viz-design.md §7) is engine-neutral:
``{id, name, type, aliases, chunk_ids, document_ids}`` for nodes and
``{id, source, target, rel_type, chunk_ids, document_ids}`` for edges (``source``/
``target`` are node ids so the payload drops into ``force-graph``). The Graphiti
re-map adds **temporal** fields (``fact``, ``valid_at``, ``invalid_at``) on edges.

Provenance: a Graphiti ``EntityEdge`` carries ``episodes`` — and because we ingest
with ``uuid = point_id``, those episode uuids ARE the Qdrant chunk_ids (G6). Nodes
don't carry episodes directly, so their ``chunk_ids`` are empty (provenance lives on
the facts). ``type`` is the first non-base label (Graphiti tags every entity with the
base ``Entity`` label plus its ontology type)."""

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


def node_to_dto(node: Any) -> dict[str, Any]:
    """Graphiti ``EntityNode`` → wire node DTO. Tolerant of missing attrs."""
    labels = list(getattr(node, "labels", None) or [])
    return {
        "id": getattr(node, "uuid", "") or "",
        "name": getattr(node, "name", "") or "",
        "type": _entity_type(labels),
        "aliases": [],  # Graphiti folds aliases into resolution; not surfaced per-node
        "chunk_ids": [],  # provenance lives on facts (edges), not entity nodes
        "document_ids": [],
        "summary": getattr(node, "summary", "") or "",
    }


def edge_to_dto(edge: Any) -> dict[str, Any]:
    """Graphiti ``EntityEdge`` (a RELATES_TO fact) → wire edge DTO.

    ``rel_type`` is the relation name (``LIVES_IN``); ``chunk_ids`` are the supporting
    episode uuids (== Qdrant point_ids). Temporal window flows through for the viz."""
    episodes = [str(e) for e in (getattr(edge, "episodes", None) or []) if e]
    return {
        "id": getattr(edge, "uuid", "") or "",
        "source": getattr(edge, "source_node_uuid", "") or "",
        "target": getattr(edge, "target_node_uuid", "") or "",
        "rel_type": getattr(edge, "name", "") or "",
        "fact": getattr(edge, "fact", "") or "",
        "chunk_ids": episodes,
        "document_ids": [],
        "valid_at": _iso(getattr(edge, "valid_at", None)),
        "invalid_at": _iso(getattr(edge, "invalid_at", None)),
    }


__all__ = ["edge_to_dto", "node_to_dto"]
