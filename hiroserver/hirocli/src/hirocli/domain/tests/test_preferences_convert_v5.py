"""The one-time preferences v4 → v5 conversion: embedding and reranker profiles (``convert_v5``).

Every leg must end up with the model it used in v4 (its override, else the workspace default), so search and the
embedder locks behave as before.
"""

from __future__ import annotations

import json
from pathlib import Path

from hirocli.domain.preferences import (
    load_preferences,
    preferences_file,
    resolve_graph_reranker_model,
    resolve_graph_reranker_profile,
    resolve_graphiti_embedder_model,
    resolve_knowledge_embedder_model,
    resolve_knowledge_reranker_model,
    resolve_knowledge_reranker_profile,
)
from hirocli.domain.preferences.convert_v5 import PREFERENCES_V4_BACKUP, convert_preferences_v4_to_v5


def _write(ws: Path, data: dict) -> None:
    ws.mkdir(parents=True, exist_ok=True)
    preferences_file(ws).write_text(json.dumps(data), encoding="utf-8")


def test_defaults_only_become_one_profile_per_family_used_by_both_legs(tmp_path: Path) -> None:
    # env0's and Simone's shape: the two defaults set, no override. voyage:rerank-2.5 is no longer in the catalog
    # and is kept as it is (the model is checked for its form only).
    ws = tmp_path / "ws"
    v4 = {
        "version": 4,
        "llm": {"default_embedder": "openai:text-embedding-3-small", "default_reranker": "voyage:rerank-2.5"},
        "graph": {"embedder_model": None, "reranker": {"model_id": None, "min_relevance": 0.3, "device": None}},
        "knowledge": {
            "default_embedding_model": None,
            "retrieval": {"reranker": {"enabled": False, "model_id": None, "top_n": 8, "device": None, "batch_size": 32}},
        },
    }
    _write(ws, v4)

    prefs = load_preferences(ws)

    assert prefs.version == 5
    assert prefs.embedding.profiles["default-embedder"].label == "Default embedder"
    assert list(prefs.embedding.profiles) == ["default-embedder"]
    assert list(prefs.rerank.profiles) == ["default-reranker"]
    assert prefs.graph.embedder_profile == prefs.knowledge.embedder_profile == "default-embedder"
    assert prefs.graph.reranker.profile == prefs.knowledge.retrieval.reranker.profile == "default-reranker"
    # The same models as before, for every leg.
    assert resolve_graphiti_embedder_model(prefs) == resolve_knowledge_embedder_model(prefs) == "openai:text-embedding-3-small"
    assert resolve_graph_reranker_model(prefs) == resolve_knowledge_reranker_model(prefs) == "voyage:rerank-2.5"
    # What the legs kept: the relevance floor, enabled, top N.
    assert prefs.graph.reranker.min_relevance == 0.3
    assert prefs.knowledge.retrieval.reranker.enabled is False and prefs.knowledge.retrieval.reranker.top_n == 8

    saved = json.loads(preferences_file(ws).read_text(encoding="utf-8"))
    assert saved["version"] == 5
    assert "default_embedder" not in saved["llm"] and "default_reranker" not in saved["llm"]
    assert "embedder_model" not in saved["graph"]
    assert set(saved["graph"]["reranker"]) == {"profile", "min_relevance"}
    assert "default_embedding_model" not in saved["knowledge"]
    assert set(saved["knowledge"]["retrieval"]["reranker"]) == {"enabled", "profile", "top_n"}
    assert json.loads((ws / PREFERENCES_V4_BACKUP).read_text(encoding="utf-8")) == v4

    # A v5 file is never converted again.
    again = load_preferences(ws)
    assert again.model_dump() == prefs.model_dump()


def test_overrides_get_profiles_of_their_own_and_the_default_is_kept(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    data = {
        "version": 4,
        "llm": {"default_embedder": "openai:text-embedding-3-small", "default_reranker": "cohere:rerank-v5.0-fast"},
        "graph": {
            "embedder_model": "google:gemini-embedding-001",
            "reranker": {"model_id": "local:bge-reranker-base", "device": "cuda"},
        },
        "knowledge": {
            "default_embedding_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            "retrieval": {"reranker": {"model_id": "local:bge-reranker-base", "device": "cpu"}},
        },
    }
    out, summary = convert_preferences_v4_to_v5(ws, data)

    embedding = out["embedding"]["profiles"]
    rerank = out["rerank"]["profiles"]
    # The default no leg uses is kept, so the choice isn't lost.
    assert embedding["default-embedder"] == {"label": "Default embedder", "model": "openai:text-embedding-3-small"}
    assert embedding["graph-embedder"]["model"] == "google:gemini-embedding-001"
    assert embedding["knowledge-embedder"]["model"] == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    # The same model on two devices is two profiles.
    assert rerank["graph-reranker"] == {"label": "Memory reranker", "model": "local:bge-reranker-base", "device": "cuda"}
    assert rerank["knowledge-reranker"]["device"] == "cpu"
    assert rerank["default-reranker"]["model"] == "cohere:rerank-v5.0-fast"
    assert out["graph"]["embedder_profile"] == "graph-embedder"
    assert out["knowledge"]["retrieval"]["reranker"]["profile"] == "knowledge-reranker"
    assert not summary.skipped
    assert data["version"] == 4  # the input isn't changed


def test_legs_sharing_a_model_share_its_profile(tmp_path: Path) -> None:
    data = {
        "version": 4,
        "graph": {"embedder_model": "openai:text-embedding-3-small", "reranker": {"model_id": "voyage:rerank-3"}},
        "knowledge": {
            "default_embedding_model": "openai:text-embedding-3-small",
            "retrieval": {"reranker": {"model_id": "voyage:rerank-3"}},
        },
    }
    out, _ = convert_preferences_v4_to_v5(tmp_path, data)
    assert list(out["embedding"]["profiles"]) == ["graph-embedder"]
    assert out["knowledge"]["embedder_profile"] == "graph-embedder"
    assert list(out["rerank"]["profiles"]) == ["graph-reranker"]
    assert out["knowledge"]["retrieval"]["reranker"]["profile"] == "graph-reranker"


def test_nothing_set_makes_no_profile_and_no_pick(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    _write(ws, {"version": 4})
    prefs = load_preferences(ws)
    assert prefs.embedding.profiles == {} and prefs.rerank.profiles == {}
    assert prefs.graph.embedder_profile is None and prefs.knowledge.embedder_profile is None
    assert resolve_graph_reranker_profile(prefs) is None and resolve_knowledge_reranker_profile(prefs) is None


def test_a_model_in_a_refused_form_is_skipped_not_fatal(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    _write(ws, {"version": 4, "llm": {"default_embedder": "no-colon-here", "default_reranker": "voyage:rerank-3"}})
    prefs = load_preferences(ws)  # never fails the load
    assert prefs.embedding.profiles == {}
    assert prefs.graph.embedder_profile is None
    assert resolve_graph_reranker_model(prefs) == "voyage:rerank-3"
