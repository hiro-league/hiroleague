"""Unit tests for ``KnowledgeRetrievalNodes`` branch coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hirocli.domain.preferences import ResolvedModel, WorkspacePreferences
from hirocli.runtime.agent_graph.ledger import LedgerSink
from hirocli.runtime.agent_graph.services import AgentServices
from hirocli.runtime.tests.graph_fakes import FakeKnowledgeService, knowledge_hit
import hirocli.services.knowledge.agent.rewrite_support as rewrite_support_module
from hirocli.services.knowledge.agent import KnowledgeGraphConfig
from hirocli.services.knowledge.agent.helpers import NormalizedQuery, QueryRewrite
from hirocli.services.knowledge.agent.legs import RetrievalLeg
from hirocli.services.knowledge.agent.retrieval_nodes import KnowledgeRetrievalNodes


def _nodes(
    tmp_path: Path,
    *,
    service: Any | None = None,
    prefs: WorkspacePreferences | None = None,
) -> KnowledgeRetrievalNodes:
    services = AgentServices(
        workspace_path=tmp_path,
        ledger_sink=LedgerSink(tmp_path),
    )
    return KnowledgeRetrievalNodes(
        services,
        KnowledgeGraphConfig(
            service=service or FakeKnowledgeService(),
            prefs=prefs or WorkspacePreferences(),
        ),
    )


def _normalized(text: str = "what is hiro?") -> NormalizedQuery:
    return NormalizedQuery(raw=text, text=text, language="en")


@pytest.mark.asyncio
async def test_rewrite_query_node_off(tmp_path: Path) -> None:
    nodes = _nodes(tmp_path)
    out = await nodes.rewrite_query_node({"rewrite": False, "normalized_query": _normalized()})
    assert out == {}


@pytest.mark.asyncio
async def test_rewrite_query_node_no_llm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        rewrite_support_module,
        "resolve_knowledge_rewrite_llm",
        lambda *_a, **_k: None,
    )
    nodes = _nodes(tmp_path)
    out = await nodes.rewrite_query_node({"rewrite": True, "normalized_query": _normalized()})
    assert out == {}


@pytest.mark.asyncio
async def test_rewrite_query_node_parse_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeModel:
        async def ainvoke(self, _messages):
            return {"parsed": None, "raw": None, "parsing_error": "bad json"}

    monkeypatch.setattr(
        rewrite_support_module,
        "resolve_knowledge_rewrite_llm",
        lambda *_a, **_k: ResolvedModel(
            model_id="google:gemini-3-flash-preview",
            temperature=0.0,
            max_tokens=1024,
        ),
    )
    monkeypatch.setattr(
        rewrite_support_module,
        "get_model_catalog",
        lambda: type("C", (), {"get_model": lambda _s, _m: type("S", (), {"features": ["structured_output"]})()})(),
    )
    monkeypatch.setattr(
        "hirocli.services.knowledge.agent.retrieval_nodes.create_chat_model",
        lambda *_a, **_k: _FakeModel(),
    )
    monkeypatch.setattr(
        "hirocli.services.knowledge.agent.retrieval_nodes.with_structured_output_compat",
        lambda model, *_a, **_k: model,
    )
    nodes = _nodes(tmp_path)
    out = await nodes.rewrite_query_node({"rewrite": True, "normalized_query": _normalized()})
    assert out == {}


@pytest.mark.asyncio
async def test_rewrite_query_node_no_structured_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[bool] = []

    class _FakeModel:
        async def ainvoke(self, _messages):
            called.append(True)
            return {}

    monkeypatch.setattr(
        rewrite_support_module,
        "resolve_knowledge_rewrite_llm",
        lambda *_a, **_k: ResolvedModel(
            model_id="google:gemini-3-flash-preview",
            temperature=0.0,
            max_tokens=1024,
        ),
    )
    monkeypatch.setattr(
        rewrite_support_module,
        "get_model_catalog",
        lambda: type("C", (), {"get_model": lambda _s, _m: type("S", (), {"features": []})()})(),
    )
    monkeypatch.setattr(
        "hirocli.services.knowledge.agent.retrieval_nodes.create_chat_model",
        lambda *_a, **_k: _FakeModel(),
    )
    nodes = _nodes(tmp_path)
    out = await nodes.rewrite_query_node({"rewrite": True, "normalized_query": _normalized()})
    assert out == {}
    assert called == []


@pytest.mark.asyncio
async def test_rewrite_query_node_call_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _BoomModel:
        async def ainvoke(self, _messages):
            raise RuntimeError("provider down")

    monkeypatch.setattr(
        rewrite_support_module,
        "resolve_knowledge_rewrite_llm",
        lambda *_a, **_k: ResolvedModel(
            model_id="google:gemini-3-flash-preview",
            temperature=0.0,
            max_tokens=1024,
        ),
    )
    monkeypatch.setattr(
        rewrite_support_module,
        "get_model_catalog",
        lambda: type("C", (), {"get_model": lambda _s, _m: type("S", (), {"features": ["structured_output"]})()})(),
    )
    monkeypatch.setattr(
        "hirocli.services.knowledge.agent.retrieval_nodes.create_chat_model",
        lambda *_a, **_k: _BoomModel(),
    )
    monkeypatch.setattr(
        "hirocli.services.knowledge.agent.retrieval_nodes.with_structured_output_compat",
        lambda model, *_a, **_k: model,
    )
    nodes = _nodes(tmp_path)
    out = await nodes.rewrite_query_node({"rewrite": True, "normalized_query": _normalized()})
    assert out == {}


@pytest.mark.asyncio
async def test_rewrite_query_node_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeModel:
        async def ainvoke(self, _messages):
            return {
                "parsed": QueryRewrite(
                    standalone_query="hiro assistant",
                    keywords=["Hiro"],
                    knowledge_needed=True,
                    entities=["Hiro"],
                ),
                "raw": None,
            }

    monkeypatch.setattr(
        rewrite_support_module,
        "resolve_knowledge_rewrite_llm",
        lambda *_a, **_k: ResolvedModel(
            model_id="google:gemini-3-flash-preview",
            temperature=0.0,
            max_tokens=1024,
        ),
    )
    monkeypatch.setattr(
        rewrite_support_module,
        "get_model_catalog",
        lambda: type("C", (), {"get_model": lambda _s, _m: type("S", (), {"features": ["structured_output"]})()})(),
    )
    monkeypatch.setattr(
        "hirocli.services.knowledge.agent.retrieval_nodes.create_chat_model",
        lambda *_a, **_k: _FakeModel(),
    )
    monkeypatch.setattr(
        "hirocli.services.knowledge.agent.retrieval_nodes.with_structured_output_compat",
        lambda model, *_a, **_k: model,
    )
    nodes = _nodes(tmp_path)
    out = await nodes.rewrite_query_node({"rewrite": True, "normalized_query": _normalized()})
    assert out["knowledge_needed"] is True
    assert out["rewritten_query"] == "hiro assistant"


@pytest.mark.asyncio
async def test_graph_expand_node_graph_mode_off(tmp_path: Path) -> None:
    nodes = _nodes(tmp_path)
    out = await nodes.graph_expand_node({"graph_mode": "off", "query": "hi"})
    assert out["effective_leg"] == RetrievalLeg.FLAT.value


@pytest.mark.asyncio
async def test_graph_expand_node_no_graph_db(tmp_path: Path) -> None:
    nodes = _nodes(tmp_path)
    out = await nodes.graph_expand_node({"graph_mode": "graphiti", "query": "hi"})
    assert out["effective_leg"] == RetrievalLeg.FLAT.value


@pytest.mark.asyncio
async def test_vector_search_node_empty_vector(tmp_path: Path) -> None:
    nodes = _nodes(tmp_path)
    out = await nodes.vector_search_node(
        {
            "normalized_query": _normalized(),
            "query_vector": [],
            "top_k": 5,
            "min_score": 0.0,
        }
    )
    assert out == {"hits": []}


@pytest.mark.asyncio
async def test_rerank_node_disabled(tmp_path: Path) -> None:
    nodes = _nodes(tmp_path)
    out = await nodes.rerank_node(
        {"normalized_query": _normalized(), "hits": [knowledge_hit()]}
    )
    assert out == {}


@pytest.mark.asyncio
async def test_rerank_node_no_candidates(tmp_path: Path) -> None:
    prefs = WorkspacePreferences()
    prefs.knowledge.retrieval.reranker.enabled = True
    prefs.knowledge.retrieval.reranker.model_id = "local:ms-marco"
    nodes = _nodes(tmp_path, prefs=prefs)
    out = await nodes.rerank_node({"normalized_query": _normalized(), "hits": []})
    assert out == {}


@pytest.mark.asyncio
async def test_rerank_node_success(tmp_path: Path) -> None:
    prefs = WorkspacePreferences()
    prefs.knowledge.retrieval.reranker.enabled = True
    prefs.knowledge.retrieval.reranker.model_id = "local:ms-marco"
    nodes = _nodes(tmp_path, prefs=prefs)
    out = await nodes.rerank_node(
        {"normalized_query": _normalized(), "hits": [knowledge_hit()]}
    )
    assert out["reranked"] is True
    assert len(out["hits"]) == 1
