"""Tests for the Graphiti pivot additions to workspace preferences.

Pure model/validation + the embedder-id resolver (no catalog/credential needed).
Model-tier resolvers are covered for the unconfigured (None) short-circuit only;
their availability path needs a registered workspace (integration scope).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hirocli.domain.preferences import (
    DEFAULT_GRAPHITI_EXTRACTION_TUNING_PROFILE_ID,
    DEFAULT_GRAPHITI_SMALL_TUNING_PROFILE_ID,
    GraphPreferences,
    WorkspacePreferences,
    default_tuning_profiles,
    resolve_graphiti_embedder_model,
    resolve_graphiti_extraction_model,
)


def test_default_prefs_have_graph_section_off() -> None:
    prefs = WorkspacePreferences()
    assert prefs.graph.backend == "off"
    assert prefs.graph.k_hop == 1
    assert prefs.graph.temporal_default == "current"
    assert (
        prefs.graph.extraction_tuning_profile
        == DEFAULT_GRAPHITI_EXTRACTION_TUNING_PROFILE_ID
    )
    assert prefs.graph.small_tuning_profile == DEFAULT_GRAPHITI_SMALL_TUNING_PROFILE_ID


def test_graphiti_tuning_profiles_present_and_locked() -> None:
    profiles = default_tuning_profiles()
    for pid in (
        DEFAULT_GRAPHITI_EXTRACTION_TUNING_PROFILE_ID,
        DEFAULT_GRAPHITI_SMALL_TUNING_PROFILE_ID,
    ):
        assert pid in profiles
        assert profiles[pid].locked is True
        assert profiles[pid].thinking == "off"
    # Extraction tier gets the larger budget.
    assert (
        profiles[DEFAULT_GRAPHITI_EXTRACTION_TUNING_PROFILE_ID].max_tokens
        > profiles[DEFAULT_GRAPHITI_SMALL_TUNING_PROFILE_ID].max_tokens
    )


def test_default_prefs_validate() -> None:
    # Round-trips through model_validate (the validator runs the graph-profile check).
    prefs = WorkspacePreferences()
    reparsed = WorkspacePreferences.model_validate_json(prefs.model_dump_json())
    assert reparsed.graph.backend == "off"


def test_unknown_graph_tuning_profile_rejected() -> None:
    prefs = WorkspacePreferences()
    prefs.graph.extraction_tuning_profile = "does_not_exist"
    with pytest.raises(ValidationError, match="graph tuning profile"):
        WorkspacePreferences.model_validate(prefs.model_dump())


def test_invalid_backend_rejected() -> None:
    with pytest.raises(ValidationError):
        GraphPreferences(backend="nonsense")
    # "mix" was removed (only "off"/"graphiti" remain) — a stale pref must fail loud.
    with pytest.raises(ValidationError):
        GraphPreferences(backend="mix")


def test_k_hop_bounds() -> None:
    with pytest.raises(ValidationError):
        GraphPreferences(k_hop=0)
    with pytest.raises(ValidationError):
        GraphPreferences(k_hop=4)


def test_embedder_resolver_falls_back_to_knowledge_default() -> None:
    prefs = WorkspacePreferences()
    # Unset graph embedder → shares the knowledge dense embedder (G8).
    assert resolve_graphiti_embedder_model(prefs) == prefs.knowledge.default_embedding_model_resolved
    # Explicit graph embedder wins.
    prefs.graph.embedder_model = "openai:text-embedding-3-small"
    assert resolve_graphiti_embedder_model(prefs) == "openai:text-embedding-3-small"


def test_extraction_resolver_none_when_no_model_configured(tmp_path) -> None:
    # No knowledge.answering.model and no llm.default_chat → None before any
    # catalog/credential lookup (so this stays a pure unit test).
    prefs = WorkspacePreferences()
    assert prefs.llm.default_chat is None
    assert resolve_graphiti_extraction_model(prefs, tmp_path, workspace_id="w") is None


def test_graph_reranker_defaults() -> None:
    # Cross-encoder reranker sub-prefs: off-by-default, no model, no gate.
    rr = WorkspacePreferences().graph.reranker
    assert rr.model_id is None  # null → reuse the shared knowledge reranker
    assert rr.min_relevance == 0.0  # keep all (gate disabled)
    assert rr.device is None


def test_graph_reranker_min_relevance_bounds() -> None:
    from hirocli.domain.preferences import KnowledgeGraphRerankerPreferences

    assert KnowledgeGraphRerankerPreferences(min_relevance=1.0).min_relevance == 1.0
    with pytest.raises(ValidationError):
        KnowledgeGraphRerankerPreferences(min_relevance=1.5)
