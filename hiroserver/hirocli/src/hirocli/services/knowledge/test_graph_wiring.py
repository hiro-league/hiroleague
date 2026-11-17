"""The core's hand-in to the knowledge engine: preferences → settings, models, reranker, graph leg."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from hiro_memory.knowledge.settings import KnowledgeSettings
from hiro_memory.testing import FakeKnowledgeRetriever, knowledge_hit

import hirocli.services.knowledge.graph_wiring as graph_wiring_module
from hirocli.domain.preferences import ResolvedModel, WorkspacePreferences
from hirocli.services.knowledge.graph_wiring import knowledge_graph_config, knowledge_settings


def _catalog(features: list[str]):
    return type("C", (), {"get_model": lambda _s, _m: SimpleNamespace(features=features)})()


def _resolved() -> ResolvedModel:
    return ResolvedModel(model_id="google:gemini-3-flash-preview", temperature=0.0, max_tokens=1024, thinking="low")


def test_settings_carry_the_preferences_values() -> None:
    prefs = WorkspacePreferences.model_validate(
        {
            "knowledge": {
                "retrieval": {
                    "top_k": 7,
                    "min_score": 0.25,
                    "hybrid": False,
                    "prefetch_limit": 50,
                    "reranker": {"enabled": True, "top_n": 3},
                },
                "answering": {"prompt": "Be brief.", "cite_sources": False, "language_policy": "prefer_arabic"},
                "rewrite": {"prompt": "Rewrite it."},
            },
            "graph": {"temporal_default": "current"},
        }
    )
    assert knowledge_settings(prefs) == KnowledgeSettings.model_validate(
        {
            "retrieval": {
                "top_k": 7,
                "min_score": 0.25,
                "hybrid": False,
                "prefetch_limit": 50,
                "reranker": {"enabled": True, "top_n": 3},
            },
            "answering": {"prompt": "Be brief.", "cite_sources": False, "language_policy": "prefer_arabic"},
            "rewrite": {"prompt": "Rewrite it."},
            "graph_temporal_default": "current",
        }
    )


def test_default_preferences_give_the_engine_defaults() -> None:
    assert knowledge_settings(WorkspacePreferences()) == KnowledgeSettings()


def test_rewrite_model_none_without_a_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph_wiring_module, "resolve_knowledge_rewrite_llm", lambda *_a, **_k: None)
    config = knowledge_graph_config(FakeKnowledgeRetriever(), WorkspacePreferences(), tmp_path)
    assert config.rewrite_model() is None


@pytest.mark.parametrize(("features", "expected"), [([], False), (["structured_output"], True)])
def test_rewrite_model_reports_structured_output_from_the_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, features: list[str], expected: bool
) -> None:
    monkeypatch.setattr(graph_wiring_module, "resolve_knowledge_rewrite_llm", lambda *_a, **_k: _resolved())
    monkeypatch.setattr(graph_wiring_module, "get_model_catalog", lambda: _catalog(features))
    model = knowledge_graph_config(FakeKnowledgeRetriever(), WorkspacePreferences(), tmp_path).rewrite_model()
    assert model is not None
    assert model.model_id == "google:gemini-3-flash-preview"
    assert (model.temperature, model.max_tokens, model.thinking) == (0.0, 1024, "low")
    assert model.structured_output is expected


def test_answering_model_builds_through_the_model_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(graph_wiring_module, "resolve_knowledge_answering_llm", lambda *_a, **_k: _resolved())
    monkeypatch.setattr(
        graph_wiring_module, "create_chat_model", lambda model_id, **kwargs: calls.append((model_id, kwargs)) or "m"
    )
    config = knowledge_graph_config(FakeKnowledgeRetriever(), WorkspacePreferences(), tmp_path, workspace_id="ws")
    model = config.answering_model()
    assert model is not None and model.build() == "m"
    assert calls == [
        (
            "google:gemini-3-flash-preview",
            {
                "workspace_path": tmp_path,
                "workspace_id": "ws",
                "temperature": 0.0,
                "max_tokens": 1024,
                "thinking": "low",
                "num_ctx": None,
            },
        )
    ]


@pytest.mark.asyncio
async def test_reranker_comes_from_the_rerank_profile(tmp_path: Path) -> None:
    calls: list[dict] = []

    class _Service(FakeKnowledgeRetriever):
        async def rerank_hits(self, query, hits, **kwargs):
            calls.append({"query": query, **kwargs})
            return hits

    assert knowledge_graph_config(_Service(), WorkspacePreferences(), tmp_path).reranker() is None
    prefs = WorkspacePreferences.model_validate(
        {
            "rerank": {"profiles": {"r": {"label": "R", "model": "local:ms-marco-multibert-l-12", "device": "cpu"}}},
            "knowledge": {"retrieval": {"reranker": {"enabled": True, "profile": "r"}}},
        }
    )
    reranker = knowledge_graph_config(_Service(), prefs, tmp_path, workspace_id="ws").reranker()
    assert reranker is not None and reranker.model_id == "local:ms-marco-multibert-l-12"
    await reranker.rerank("q", [knowledge_hit()], 4)
    assert calls == [
        {"query": "q", "model_id": "local:ms-marco-multibert-l-12", "top_n": 4, "device": "cpu", "workspace_id": "ws"}
    ]


def test_graph_leg_points_at_the_workspace(tmp_path: Path) -> None:
    config = knowledge_graph_config(FakeKnowledgeRetriever(), WorkspacePreferences(), tmp_path)
    assert config.graph is not None and config.graph.workspace_path == tmp_path
    assert config.embedder_model is None  # no embedding profile picked
