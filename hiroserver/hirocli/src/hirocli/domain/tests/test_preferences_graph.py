"""Tests for the Graphiti pivot additions to workspace preferences.

Pure model/validation + the embedder-id resolver (no catalog/credential needed).
Model-tier resolvers are covered for the unconfigured (None) short-circuit only;
their availability path needs a registered workspace (integration scope).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hirocli.domain.preferences import (
    JOB_PRESETS,
    GraphPreferences,
    WorkspacePreferences,
    resolve_graph_reranker_model,
    resolve_graph_reranker_profile,
    resolve_graphiti_embedder_model,
    resolve_graphiti_extraction_model,
    resolve_knowledge_embedder_model,
    resolve_knowledge_reranker_model,
    resolve_knowledge_reranker_profile,
)


def test_default_prefs_have_graph_section_off() -> None:
    prefs = WorkspacePreferences()
    assert prefs.graph.backend == "off"
    assert prefs.graph.k_hop == 2
    assert prefs.graph.temporal_default == "all"
    # Phase 7b step 5: each graph tier points at an AI profile (unset by default).
    assert prefs.graph.extraction_profile is None
    assert prefs.graph.small_profile is None


def test_graph_job_presets_are_deterministic() -> None:
    # The old graphiti_extraction / graphiti_small presets live on as the jobs' preset tuning.
    for job in ("graph_extraction", "graph_small"):
        assert JOB_PRESETS[job].thinking == "off"
        assert JOB_PRESETS[job].temperature == 0.0
    # Extraction tier gets the larger budget; small steps borrow its model when unset.
    assert JOB_PRESETS["graph_extraction"].max_tokens > JOB_PRESETS["graph_small"].max_tokens
    assert JOB_PRESETS["graph_small"].falls_back_to == "graph_extraction"


def test_default_prefs_validate() -> None:
    # Round-trips through model_validate (the validator runs the graph-profile check).
    prefs = WorkspacePreferences()
    reparsed = WorkspacePreferences.model_validate_json(prefs.model_dump_json())
    assert reparsed.graph.backend == "off"


def test_unknown_graph_ai_profile_rejected() -> None:
    prefs = WorkspacePreferences()
    prefs.graph.extraction_profile = "does_not_exist"
    # The validator reports the offending dotted path (discovered via the ai_profile_ref marker).
    with pytest.raises(
        ValidationError, match="graph.extraction_profile points at an unknown AI profile"
    ):
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


def test_search_scope_accepts_edges_and_episodes() -> None:
    # New edges+episodes ablation scope (episodes WITHOUT entity nodes).
    prefs = GraphPreferences(search_scope="edges_and_episodes", search_recipe="rrf")
    assert prefs.search_scope == "edges_and_episodes"


def test_mmr_rejected_for_all_episodes_scopes() -> None:
    # MMR has no EpisodeReranker, so it's invalid for EVERY episodes-inclusive scope.
    for scope in ("edges_and_episodes", "edges_nodes_episodes"):
        with pytest.raises(ValidationError, match="mmr"):
            GraphPreferences(search_scope=scope, search_recipe="mmr")
    # …but fine with rrf / cross_encoder.
    assert GraphPreferences(search_scope="edges_and_episodes", search_recipe="cross_encoder")


def test_embedder_resolvers_read_each_legs_profile() -> None:
    prefs = WorkspacePreferences()
    # No forced default: no profile picked → None (indexing is gated, no silent model).
    assert resolve_graphiti_embedder_model(prefs) is None
    assert resolve_knowledge_embedder_model(prefs) is None
    prefs = WorkspacePreferences.model_validate({
        "embedding": {"profiles": {
            "local": {"label": "Local", "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"},
            "small": {"label": "Small", "model": "openai:text-embedding-3-small"},
        }},
        "graph": {"embedder_profile": "small"},
        "knowledge": {"embedder_profile": "local"},
    })
    assert resolve_graphiti_embedder_model(prefs) == "openai:text-embedding-3-small"
    assert resolve_knowledge_embedder_model(prefs) == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def test_a_pick_must_name_an_existing_search_profile() -> None:
    with pytest.raises(ValidationError, match="unknown embedding profile"):
        WorkspacePreferences.model_validate({"graph": {"embedder_profile": "nope"}})
    with pytest.raises(ValidationError, match="unknown reranker profile"):
        WorkspacePreferences.model_validate({"knowledge": {"retrieval": {"reranker": {"profile": "nope"}}}})


def test_extraction_resolver_none_when_no_model_configured(tmp_path) -> None:
    # No graph.extraction_profile and no llm.chat_profile → None before any
    # catalog/credential lookup (so this stays a pure unit test).
    prefs = WorkspacePreferences()
    assert prefs.llm.chat_profile is None
    assert resolve_graphiti_extraction_model(prefs, tmp_path, workspace_id="w") is None


def test_reranker_resolvers_read_each_legs_profile() -> None:
    prefs = WorkspacePreferences()
    # No profile picked → no reranker for either leg.
    assert resolve_knowledge_reranker_model(prefs) is None
    assert resolve_graph_reranker_model(prefs) is None
    prefs = WorkspacePreferences.model_validate({
        "rerank": {"profiles": {
            "bge": {"label": "BGE", "model": "local:bge-reranker-v2-m3", "device": "cuda"},
            "voyage": {"label": "Voyage", "model": "voyage:rerank-2"},
        }},
        "graph": {"reranker": {"profile": "voyage"}},
        "knowledge": {"retrieval": {"reranker": {"profile": "bge"}}},
    })
    assert resolve_knowledge_reranker_model(prefs) == "local:bge-reranker-v2-m3"
    assert resolve_graph_reranker_model(prefs) == "voyage:rerank-2"
    # The profile carries where a local model runs.
    assert resolve_knowledge_reranker_profile(prefs).device == "cuda"
    assert resolve_graph_reranker_profile(prefs).device is None


def test_graph_reranker_defaults() -> None:
    # Cross-encoder reranker sub-prefs: no model, relevance gate at the 0.3 default.
    rr = WorkspacePreferences().graph.reranker
    assert rr.profile is None  # null → no reranker (the fact search uses RRF)
    assert rr.min_relevance == 0.3  # drop facts below 0.3 cross-encoder relevance


def test_graph_reranker_min_relevance_bounds() -> None:
    from hirocli.domain.preferences import KnowledgeGraphRerankerPreferences

    assert KnowledgeGraphRerankerPreferences(min_relevance=1.0).min_relevance == 1.0
    with pytest.raises(ValidationError):
        KnowledgeGraphRerankerPreferences(min_relevance=1.5)
