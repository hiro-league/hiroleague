"""Tests for flattened preferences schema export."""

from __future__ import annotations

from hirocli.domain.preferences_schema import (
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
    assert fields["knowledge.default_embedding_model_resolved"]["readOnly"] is True


def test_json_schema_marks_nested_properties_required() -> None:
    schema = workspace_preferences_json_schema()
    assert "knowledge" in schema["required"]
    knowledge = schema["$defs"]["KnowledgePreferences"]
    assert "chunking" in knowledge["required"]
