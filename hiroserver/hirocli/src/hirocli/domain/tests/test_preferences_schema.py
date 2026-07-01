"""Tests for flattened preferences schema export."""

from __future__ import annotations

from hirocli.domain.preferences.computed_fields import COMPUTED_PREFERENCE_FIELDS
from hirocli.domain.preferences.defaults import pref_field
from hirocli.domain.preferences_schema import (
    _META_KEYS,
    _walk_node,
    workspace_preferences_field_map,
    workspace_preferences_json_schema,
    workspace_preferences_schema_payload,
)


def test_chunking_fields_expose_bounds_and_descriptions() -> None:
    fields = workspace_preferences_field_map()

    chunk_size = fields["knowledge.chunking.chunk_size"]
    assert chunk_size["type"] == "integer"
    assert chunk_size["default"] == 1200
    assert chunk_size["min"] == 200
    assert chunk_size["max"] == 8000
    assert chunk_size["description"]

    chunk_overlap = fields["knowledge.chunking.chunk_overlap"]
    assert chunk_overlap["min"] == 0
    assert chunk_overlap["max"] == 2000
    assert chunk_overlap["description"]

    embed_ctx = fields["knowledge.chunking.embed_structural_context"]
    assert embed_ctx["type"] == "boolean"
    assert embed_ctx["default"] is True
    assert "re-ingest" in embed_ctx["description"].lower()

    respect_headings = fields["knowledge.chunking.markdown.respect_headings"]
    assert respect_headings["type"] == "boolean"
    assert respect_headings["description"]


def test_advanced_flag_surfaces_and_defaults_absent() -> None:
    """`json_schema_extra={"advanced": True}` reaches the flat field map; basic fields omit it."""
    fields = workspace_preferences_field_map()
    # Seeded demo advanced field (see KnowledgeChunkingPreferences.embed_structural_context).
    assert fields["knowledge.chunking.embed_structural_context"]["advanced"] is True
    # Untagged fields stay basic — the key is absent (default), not False.
    assert "advanced" not in fields["knowledge.chunking.chunk_size"]


def test_embedding_model_is_nullable_with_model_kind() -> None:
    fields = workspace_preferences_field_map()
    embed = fields["knowledge.default_embedding_model"]
    assert embed["type"] == "string"
    assert embed["nullable"] is True
    assert embed["model_kind"] == "embedding"
    assert embed["description"]


def test_literal_enum_surfaces_on_leaf() -> None:
    fields = workspace_preferences_field_map()
    backend = fields["graph.backend"]
    assert backend["enum"] == ["off", "graphiti"]
    assert backend["default"] == "off"


def test_schema_payload_includes_version_and_fields() -> None:
    payload = workspace_preferences_schema_payload()
    assert payload["preferences_version"] == 3
    assert "knowledge.chunking.chunk_size" in payload["fields"]


def test_field_map_tags_for_save_policy() -> None:
    fields = workspace_preferences_field_map()
    assert fields["version"]["readOnly"] is True
    assert fields["tuning_profiles"]["writeWhole"] is True
    assert fields["graph.eval.answer_prompts"]["writeWhole"] is True
    assert fields["llm.default_chat"]["model_kind"] == "chat"
    assert fields["llm.default_chat"]["nullable"] is True
    assert fields["graph.reranker.device"]["nullable"] is True
    assert fields["image_profiles"]["preferencesSaveSkip"] is True
    assert fields["knowledge.default_embedding_model_locked"]["readOnly"] is True
    assert fields["graph.embedder_model_locked"]["readOnly"] is True
    assert fields["llm.default_embedder"]["model_kind"] == "embedding"


def test_json_schema_marks_nested_properties_required() -> None:
    schema = workspace_preferences_json_schema()
    assert "knowledge" in schema["required"]
    knowledge = schema["$defs"]["KnowledgePreferences"]
    assert "chunking" in knowledge["required"]


def test_pref_field_metadata_keys_are_all_surfaced() -> None:
    """Drift guard: every admin-facing key ``pref_field`` can emit must be copied into the flat field
    map (``_META_KEYS``). Otherwise a newly added knob (e.g. a future save-policy flag) would live on
    the model but silently never reach the admin UI. The one backend-only marker
    (``tuning_profile_ref``) is intentionally excluded — see the ``pref_field`` docstring."""
    field = pref_field(
        model_kind="chat",
        advanced=True,
        step=1.0,
        save_skip=True,
        write_whole=True,
        read_only=True,
        tuning_profile_ref=True,
        default=None,
    )
    emitted = set(field.json_schema_extra.keys())
    backend_only = {"tuning_profile_ref"}
    missing = (emitted - backend_only) - set(_META_KEYS)
    assert missing == set(), f"pref_field emits metadata keys absent from _META_KEYS: {missing}"


def test_computed_field_paths_are_disjoint_and_attach_to_real_parents() -> None:
    """Drift guard for the computed read-only enrichments: a computed path must not shadow a persisted
    leaf, and it must hang off a real object in the persisted schema — so a typo'd path (which the
    string ``ComputedPreferenceField.path`` can't catch on its own) can't create an unreachable field
    that silently overwrites nothing on the UI."""
    root = workspace_preferences_json_schema()
    persisted: dict = {}
    _walk_node("", root, root, persisted)
    computed = {cf.path for cf in COMPUTED_PREFERENCE_FIELDS}

    collisions = computed & set(persisted)
    assert not collisions, f"computed field paths collide with persisted paths: {collisions}"

    for path in computed:
        parent = path.rsplit(".", 1)[0]
        assert any(p == parent or p.startswith(f"{parent}.") for p in persisted), (
            f"computed field {path!r} has no real parent object {parent!r} in the persisted schema"
        )
