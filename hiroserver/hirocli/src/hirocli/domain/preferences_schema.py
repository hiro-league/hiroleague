"""Flatten ``WorkspacePreferences`` JSON Schema into dotted paths for the admin UI."""

from __future__ import annotations

from typing import Any

from hirocli.domain.preferences import WorkspacePreferences

# Keys copied from a property node into the flat field map (plus derived flags).
# ``minimum``/``maximum`` are intentionally absent: they are re-emitted as ``min``/``max``
# by ``_leaf_meta`` (the single representation the frontend reads), so copying them too
# would just duplicate the bounds in every numeric field.
#
# ``advanced`` is a display-only flag (``json_schema_extra={"advanced": True}`` on the field):
# the admin UI hides advanced fields behind a "show advanced" toggle. Absent ⇒ basic. It never
# affects PATCH writes — it's purely a presentation hint carried through the schema map.
_META_KEYS = (
    "type",
    "default",
    "step",
    "enum",
    "description",
    "readOnly",
    "writeWhole",
    "preferencesSaveSkip",
    "model_kind",
    "advanced",
)

# GET /preferences enrichments — not persisted; excluded from PATCH via schema readOnly.
_PREFERENCES_PAYLOAD_READONLY_FIELDS: dict[str, dict[str, Any]] = {
    "knowledge.default_embedding_model_locked": {
        "path": "knowledge.default_embedding_model_locked",
        "type": "boolean",
        "readOnly": True,
    },
    "graph.embedder_model_locked": {
        "path": "graph.embedder_model_locked",
        "type": "boolean",
        "readOnly": True,
    },
    "knowledge.answering.model_resolved": {
        "path": "knowledge.answering.model_resolved",
        "type": "string",
        "nullable": True,
        "readOnly": True,
    },
    "knowledge.answering.model_resolved_source": {
        "path": "knowledge.answering.model_resolved_source",
        "type": "string",
        "nullable": True,
        "readOnly": True,
    },
    "graph.embedder_model_resolved": {
        "path": "graph.embedder_model_resolved",
        "type": "string",
        "nullable": True,
        "readOnly": True,
    },
}


def _resolve_ref(node: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    ref = node.get("$ref")
    if not ref:
        return node
    if not ref.startswith("#/"):
        raise ValueError(f"Unsupported $ref: {ref}")
    target: Any = root
    for part in ref[2:].split("/"):
        target = target[part]
    if not isinstance(target, dict):
        raise TypeError(f"$ref {ref} did not resolve to an object")
    return target


def _split_nullable(node: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    variants = node.get("anyOf") or node.get("oneOf")
    if not variants:
        return node, False

    null_variants = [v for v in variants if v.get("type") == "null"]
    non_null = [v for v in variants if v.get("type") != "null"]
    nullable = bool(null_variants)
    if len(non_null) != 1:
        return node, nullable

    effective = dict(non_null[0])
    for key, value in node.items():
        if key in ("anyOf", "oneOf"):
            continue
        if key not in effective:
            effective[key] = value
    return effective, nullable


def _leaf_meta(path: str, node: dict[str, Any]) -> dict[str, Any]:
    effective, nullable = _split_nullable(node)
    meta: dict[str, Any] = {"path": path, "nullable": nullable}
    for key in _META_KEYS:
        if key in effective:
            meta[key] = effective[key]
        elif key in node:
            meta[key] = node[key]
    if "type" not in meta and "enum" in meta:
        meta["type"] = "string"
    if "minimum" in effective:
        meta["min"] = effective["minimum"]
    if "maximum" in effective:
        meta["max"] = effective["maximum"]
    return meta


def _walk_node(path: str, node: dict[str, Any], root: dict[str, Any], out: dict[str, dict[str, Any]]) -> None:
    raw = _resolve_ref(node, root)
    effective, _ = _split_nullable(raw)

    if effective.get("type") == "object" or "properties" in effective:
        properties = effective.get("properties")
        if properties:
            for name, child in properties.items():
                child_path = f"{path}.{name}" if path else name
                _walk_node(child_path, child, root, out)
            return

        if "additionalProperties" in effective:
            out[path] = _leaf_meta(path, raw)
            return

    out[path] = _leaf_meta(path, raw)


def workspace_preferences_field_map() -> dict[str, dict[str, Any]]:
    """Return ``dotted.path`` → field metadata for every persisted preference leaf/object."""
    root_schema = workspace_preferences_json_schema()
    out: dict[str, dict[str, Any]] = {}
    _walk_node("", root_schema, root_schema, out)
    out.update(_PREFERENCES_PAYLOAD_READONLY_FIELDS)
    return out


def mark_schema_properties_required(schema: dict[str, Any]) -> None:
    """Mark every object property as required so TS codegen matches persisted shape."""
    if "$defs" in schema:
        for defn in schema["$defs"].values():
            if isinstance(defn, dict):
                mark_schema_properties_required(defn)

    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return

    schema["required"] = list(properties.keys())
    for child in properties.values():
        if isinstance(child, dict):
            mark_schema_properties_required(child)


def workspace_preferences_json_schema() -> dict[str, Any]:
    """JSON Schema for ``WorkspacePreferences`` with required fields for frontend codegen."""
    schema = WorkspacePreferences.model_json_schema()
    mark_schema_properties_required(schema)
    return schema


def workspace_preferences_defaults() -> dict[str, Any]:
    """Built-in default preference values (``WorkspacePreferences()``)."""
    return WorkspacePreferences().model_dump(mode="json")


def workspace_preferences_schema_payload() -> dict[str, Any]:
    """Admin API payload: static schema map keyed by dotted preference paths."""
    return {
        "preferences_version": WorkspacePreferences.model_fields["version"].default,
        "fields": workspace_preferences_field_map(),
    }
