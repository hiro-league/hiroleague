"""Computed / enriched preference fields — single source for the GET-payload enrichments.

These are NOT persisted: they're derived at read time (resolved model ids, "locked while indexed"
flags) and surfaced read-only on ``GET/PATCH /preferences``. Each one used to be declared TWICE —
its schema metadata in ``preferences_schema._PREFERENCES_PAYLOAD_READONLY_FIELDS`` and its value
computed inline in the route's ``_prefs_payload`` — so adding one meant editing both, and the two
could drift. This registry is the single place: every entry both declares its schema metadata AND
computes its value.

This registry is the one place: ``schema_meta`` feeds the field map (so the admin UI types + save
policy see the read-only field), and ``compute`` (when set) feeds the payload. Compute functions defer
their service imports to call time, so importing this module stays cheap for the codegen path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .models import WorkspacePreferences

# (prefs, workspace_path, workspace_id) -> value. Uniform signature; unused args ignored.
ComputeFn = Callable[[WorkspacePreferences, Path, str | None], Any]


@dataclass(frozen=True)
class ComputedPreferenceField:
    """One read-only enrichment: its schema metadata + how to compute its value."""

    path: str
    # Schema-map metadata for this field (``path`` is added automatically). Mirrors what a real
    # leaf carries: ``type`` (+ ``nullable``) and ``readOnly`` so it's excluded from PATCH writes.
    schema_meta: dict[str, Any]
    # Value producer for the GET payload — every computed field is populated (no schema-only entries).
    compute: ComputeFn


def _knowledge_answering_model_resolved(
    prefs: WorkspacePreferences, workspace_path: Path, workspace_id: str | None
) -> str | None:
    from .resolvers import resolve_knowledge_answering_llm

    resolved = resolve_knowledge_answering_llm(prefs, workspace_path, workspace_id=workspace_id)
    return resolved.model_id if resolved is not None else None


def _knowledge_answering_model_resolved_source(
    prefs: WorkspacePreferences, workspace_path: Path, workspace_id: str | None
) -> str | None:
    from .resolvers import knowledge_answering_model_source

    return knowledge_answering_model_source(prefs)


def _knowledge_embedder_locked(
    prefs: WorkspacePreferences, workspace_path: Path, workspace_id: str | None
) -> bool:
    from hirocli.services.knowledge import count_knowledge_points

    return count_knowledge_points(workspace_path) > 0


def _graph_embedder_locked(
    prefs: WorkspacePreferences, workspace_path: Path, workspace_id: str | None
) -> bool:
    # Graph embedder locks independently, on graph (not knowledge) indexing — read from the
    # graph-indexed marker (the Kuzu DB can't be opened to count while the server holds it).
    from hirocli.services.knowledge.graph.graph_index_marker import is_graph_indexed

    return is_graph_indexed(workspace_path)


# Order mirrors the field map output exactly (these entries are appended to the schema map), so the
# generated field-schema stays byte-stable.
COMPUTED_PREFERENCE_FIELDS: tuple[ComputedPreferenceField, ...] = (
    ComputedPreferenceField(
        "knowledge.default_embedding_model_locked",
        {"type": "boolean", "readOnly": True},
        _knowledge_embedder_locked,
    ),
    ComputedPreferenceField(
        "graph.embedder_model_locked",
        {"type": "boolean", "readOnly": True},
        _graph_embedder_locked,
    ),
    ComputedPreferenceField(
        "knowledge.answering.model_resolved",
        {"type": "string", "nullable": True, "readOnly": True},
        _knowledge_answering_model_resolved,
    ),
    ComputedPreferenceField(
        "knowledge.answering.model_resolved_source",
        {"type": "string", "nullable": True, "readOnly": True},
        _knowledge_answering_model_resolved_source,
    ),
)


def computed_preference_schema_fields() -> dict[str, dict[str, Any]]:
    """Schema-map entries for every computed field (``path`` → metadata)."""
    return {cf.path: {"path": cf.path, **cf.schema_meta} for cf in COMPUTED_PREFERENCE_FIELDS}
