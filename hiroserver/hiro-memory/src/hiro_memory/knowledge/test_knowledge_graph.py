"""The knowledge graph driven only by what an owner hands in: fakes for the engine, models and reranker.

These pin the hand-in contract (``KnowledgeGraphConfig``): when each callable runs, what a missing model or reranker
does, and that usage reaches the owner's emitter. The core's own wiring is tested in the core.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from hiro_memory.knowledge.agent import (
    KnowledgeAgentGraph,
    KnowledgeGraphConfig,
    KnowledgeModel,
    KnowledgeReranker,
)
from hiro_memory.knowledge.agent.helpers import NormalizedQuery, QueryRewrite
from hiro_memory.knowledge.agent.legs import RetrievalLeg
from hiro_memory.knowledge.agent.retrieval_nodes import KnowledgeRetrievalNodes
from hiro_memory.knowledge.settings import KnowledgeSettings
from hiro_memory.ledger.node_group import LedgerSinkRef
from hiro_memory.testing import FakeKnowledgeRetriever, RecordingLedgerSink, knowledge_hit


def _normalized(text: str = "what is hiro?") -> NormalizedQuery:
    return NormalizedQuery(raw=text, text=text, language="en")


def _model(reply: Any, *, structured_output: bool = True, built: list | None = None) -> KnowledgeModel:
    class _Fake:
        async def ainvoke(self, _messages):
            if isinstance(reply, Exception):
                raise reply
            return reply

    def build():
        if built is not None:
            built.append(True)
        return _Fake()

    return KnowledgeModel(
        model_id="fake:model", build=build, temperature=0.2, max_tokens=800, structured_output=structured_output
    )


def _nodes(tmp_path: Path, **config: Any) -> KnowledgeRetrievalNodes:
    config.setdefault("engine", FakeKnowledgeRetriever())
    return KnowledgeRetrievalNodes(
        LedgerSinkRef(RecordingLedgerSink(tmp_path)),
        KnowledgeGraphConfig(structured_output=lambda model, _schema: model, **config),
    )


# --- rewrite -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rewrite_skips_without_a_model(tmp_path: Path) -> None:
    nodes = _nodes(tmp_path)
    assert await nodes.rewrite_query_node({"rewrite": True, "normalized_query": _normalized()}) == {}


@pytest.mark.asyncio
async def test_rewrite_skips_a_model_without_structured_output(tmp_path: Path) -> None:
    built: list = []
    nodes = _nodes(tmp_path, rewrite_model=lambda: _model({}, structured_output=False, built=built))
    assert await nodes.rewrite_query_node({"rewrite": True, "normalized_query": _normalized()}) == {}
    assert built == []  # never built, never called


@pytest.mark.asyncio
async def test_rewrite_falls_back_when_the_call_fails(tmp_path: Path) -> None:
    nodes = _nodes(tmp_path, rewrite_model=lambda: _model(RuntimeError("provider down")))
    assert await nodes.rewrite_query_node({"rewrite": True, "normalized_query": _normalized()}) == {}


@pytest.mark.asyncio
async def test_rewrite_success_and_usage_reaches_the_emitter(tmp_path: Path) -> None:
    emitted: list[dict] = []
    raw = AIMessage(content="{}", usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5})
    parsed = QueryRewrite(standalone_query="hiro assistant", keywords=["Hiro"], knowledge_needed=True)
    nodes = _nodes(
        tmp_path,
        rewrite_model=lambda: _model({"parsed": parsed, "raw": raw}),
        emit_usage=lambda _writer, payload: emitted.append(payload),
    )
    out = await nodes.rewrite_query_node(
        {"rewrite": True, "normalized_query": _normalized()}, writer=lambda _e: None
    )
    assert out["rewritten_query"] == "hiro assistant"
    assert out["knowledge_needed"] is True
    assert emitted and emitted[0]["input_tokens"] == 3


# --- graph leg, search, rerank -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_expand_without_a_graph_leg_is_flat(tmp_path: Path) -> None:
    out = await _nodes(tmp_path).graph_expand_node({"graph_mode": "graphiti", "query": "hi"})
    assert out["effective_leg"] == RetrievalLeg.FLAT.value


@pytest.mark.asyncio
async def test_rerank_skips_when_disabled_or_without_a_reranker(tmp_path: Path) -> None:
    calls: list = []

    async def rerank(query, hits, top_n):
        calls.append(top_n)
        return hits

    disabled = _nodes(tmp_path, reranker=lambda: KnowledgeReranker(model_id="r:m", rerank=rerank))
    assert await disabled.rerank_node({"normalized_query": _normalized(), "hits": [knowledge_hit()]}) == {}
    enabled = KnowledgeSettings.model_validate({"retrieval": {"reranker": {"enabled": True}}})
    no_reranker = _nodes(tmp_path, settings=enabled)
    assert await no_reranker.rerank_node({"normalized_query": _normalized(), "hits": [knowledge_hit()]}) == {}
    assert calls == []


@pytest.mark.asyncio
async def test_rerank_runs_the_handed_in_reranker_with_top_n(tmp_path: Path) -> None:
    calls: list = []

    async def rerank(query, hits, top_n):
        calls.append((query, top_n))
        return list(reversed(hits))

    settings = KnowledgeSettings.model_validate({"retrieval": {"reranker": {"enabled": True, "top_n": 2}}})
    nodes = _nodes(tmp_path, settings=settings, reranker=lambda: KnowledgeReranker(model_id="r:m", rerank=rerank))
    hits = [knowledge_hit(point_id="a"), knowledge_hit(point_id="b")]
    out = await nodes.rerank_node({"normalized_query": _normalized(), "hits": hits})
    assert out["reranked"] is True
    assert [h.point_id for h in out["hits"]] == ["b", "a"]
    assert calls == [("what is hiro?", 2)]


# --- the full graph ------------------------------------------------------------------------------


def _query(**over: Any) -> dict[str, Any]:
    state: dict[str, Any] = {"query": "what is hiro?", "rewrite": False, "top_k": 5, "min_score": 0.0, "filters": {}}
    state.update(over)
    return state


@pytest.mark.asyncio
async def test_full_graph_answers_with_the_handed_in_model(tmp_path: Path) -> None:
    sink = RecordingLedgerSink(tmp_path)
    config = KnowledgeGraphConfig(
        engine=FakeKnowledgeRetriever(),
        answering_model=lambda: _model(AIMessage(content="Hiro is a local-first assistant [1].")),
    )
    compiled = KnowledgeAgentGraph(LedgerSinkRef(sink)).build(config)
    final = await compiled.ainvoke(_query())
    assert final["answer"] == "Hiro is a local-first assistant [1]."
    assert final["model_id"] == "fake:model"
    assert {"knowledge/embed_query", "knowledge/vector_search", "knowledge/call_model", "knowledge/finalize"} <= set(
        sink.nodes()
    )
    assert sink.decisions()["knowledge/call_model"][0] == "text_reply"


@pytest.mark.asyncio
async def test_full_graph_falls_back_when_the_model_cannot_be_built(tmp_path: Path) -> None:
    def broken():
        raise RuntimeError("no credentials")

    config = KnowledgeGraphConfig(
        engine=FakeKnowledgeRetriever(),
        answering_model=lambda: KnowledgeModel(model_id="fake:model", build=broken),
    )
    compiled = KnowledgeAgentGraph(LedgerSinkRef(RecordingLedgerSink(tmp_path))).build(config)
    final = await compiled.ainvoke(_query())
    assert final["answer"].startswith("Found 1 relevant source(s)")
    assert final["model_id"] == "fake:model"


@pytest.mark.asyncio
async def test_full_graph_without_a_model_answers_with_the_sources(tmp_path: Path) -> None:
    compiled = KnowledgeAgentGraph(LedgerSinkRef(RecordingLedgerSink(tmp_path))).build(
        KnowledgeGraphConfig(engine=FakeKnowledgeRetriever())
    )
    final = await compiled.ainvoke(_query())
    assert final["answer"].startswith("Found 1 relevant source(s) for: what is hiro?")
    assert final["model_id"] is None
    assert final["no_results"] is False
