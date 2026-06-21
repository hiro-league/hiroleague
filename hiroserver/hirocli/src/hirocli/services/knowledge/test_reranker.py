"""Tests for the knowledge reranker: hit reranking, normalization, registry gate, graph node."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor

from hirocli.domain.preferences import WorkspacePreferences
from hirocli.runtime.agent_graph.ledger import LedgerSink
from hirocli.runtime.agent_graph.services import AgentServices
from hirocli.services.knowledge.agent import KnowledgeGraphConfig
from hirocli.services.knowledge.agent.helpers import minmax_relevances
from hirocli.services.knowledge.agent.retrieval_nodes import KnowledgeRetrievalNodes
from hirocli.services.knowledge.models import KnowledgeSearchHit
from hirocli.services.knowledge.reranker import _normalize, rerank_hits
from hirocli.services.knowledge import reranker_registry as reg


def _hit(i: int, text: str, score: float) -> KnowledgeSearchHit:
    return KnowledgeSearchHit(
        document_id="d",
        point_id=f"p{i}",
        score=score,
        ord=i,
        text=text,
        heading_path=None,
        title="t",
        source_uri="u",
        owner_kind="system",
        owner_id="0",
        category_id=None,
        subcategory_id=None,
        tags=[],
    )


class _StubReranker(BaseDocumentCompressor):
    """Reverses the candidate order and assigns descending logits (2.0, 1.0, …)."""

    def compress_documents(self, documents, query, callbacks=None):  # type: ignore[override]
        out = []
        for rank, doc in enumerate(reversed(list(documents))):
            out.append(
                Document(
                    page_content=doc.page_content,
                    metadata={**doc.metadata, "relevance_score": 2.0 - rank},
                )
            )
        return out


# --- normalization ----------------------------------------------------------


def test_normalize_calibrated_passthrough_and_clamp() -> None:
    assert _normalize(0.42, calibrated=True) == 0.42
    assert _normalize(1.5, calibrated=True) == 1.0
    assert _normalize(-0.2, calibrated=True) == 0.0


def test_normalize_logit_uses_sigmoid() -> None:
    assert _normalize(0.0, calibrated=False) == pytest.approx(0.5)
    assert _normalize(2.0, calibrated=False) == pytest.approx(1 / (1 + math.exp(-2.0)))


def test_minmax_relevances() -> None:
    assert minmax_relevances([0.1, 0.5, 0.9]) == [0.0, 0.5, 1.0]
    # degenerate (all equal) → all 1.0; empty → empty
    assert minmax_relevances([0.3, 0.3]) == [1.0, 1.0]
    assert minmax_relevances([]) == []


# --- rerank_hits -------------------------------------------------------------


def test_rerank_hits_reorders_trims_and_normalizes() -> None:
    hits = [_hit(0, "a", 0.9), _hit(1, "b", 0.5), _hit(2, "c", 0.1)]
    out = rerank_hits(_StubReranker(), "q", hits, scores_calibrated=False, top_n=2)
    # reversed order, trimmed to top_n=2
    assert [h.point_id for h in out] == ["p2", "p1"]
    # raw logit recorded; relevance is the sigmoid of it
    assert out[0].rerank_score == 2.0
    assert out[0].relevance == pytest.approx(1 / (1 + math.exp(-2.0)))


def test_rerank_hits_empty_returns_empty() -> None:
    assert rerank_hits(_StubReranker(), "q", [], scores_calibrated=True, top_n=5) == []


# --- local registry gate -----------------------------------------------------


def test_registry_lookup() -> None:
    assert reg.is_local_reranker("local:ms-marco-multibert-l-12")
    assert not reg.is_local_reranker("cohere:rerank-v3.5")
    spec = reg.get_local_reranker("local:bge-reranker-v2-m3")
    assert spec is not None and spec.backend == "sentence_transformers"


def test_build_local_compressor_refuses_when_not_downloaded(tmp_path: Path) -> None:
    spec = reg.get_local_reranker("local:ms-marco-multibert-l-12")
    assert spec is not None
    with pytest.raises(reg.RerankerNotDownloadedError):
        reg.build_local_compressor(spec, cache_dir=tmp_path, top_n=8)


def test_download_writes_marker_and_flips_status(tmp_path: Path, monkeypatch) -> None:
    spec = reg.get_local_reranker("local:ms-marco-multibert-l-12")
    assert spec is not None
    assert not reg.is_downloaded(spec, tmp_path)

    import flashrank

    class _DummyRanker:
        def __init__(self, *a, **k) -> None:  # no network
            pass

    monkeypatch.setattr(flashrank, "Ranker", _DummyRanker)
    reg.download(spec, tmp_path)
    assert reg.is_downloaded(spec, tmp_path)


# --- cloud factory validation ------------------------------------------------


def test_create_reranker_rejects_unknown_and_wrong_kind(tmp_path: Path) -> None:
    from hirocli.domain.model_factory import create_reranker

    with pytest.raises(ValueError, match="Unknown model id"):
        create_reranker("nope:nope", workspace_path=tmp_path, workspace_id="ws")
    with pytest.raises(ValueError, match="not a rerank model"):
        create_reranker("openai:text-embedding-3-small", workspace_path=tmp_path, workspace_id="ws")


# --- graph node + build_context ----------------------------------------------


class _FakeService:
    def __init__(self, *, result=None, error: Exception | None = None) -> None:
        self._result = result or []
        self._error = error
        self.calls: list[dict] = []

    async def rerank_hits(self, query, hits, **kwargs):
        self.calls.append({"query": query, "hits": hits, **kwargs})
        if self._error is not None:
            raise self._error
        return self._result


def _graph(service, prefs: WorkspacePreferences, tmp_path: Path) -> KnowledgeRetrievalNodes:
    """Materialize a ``KnowledgeRetrievalNodes`` group for direct node-call unit tests."""
    return KnowledgeRetrievalNodes(
        AgentServices(workspace_path=tmp_path, ledger_sink=LedgerSink(tmp_path)),
        KnowledgeGraphConfig(service=service, prefs=prefs, workspace_id="ws"),
    )


def _state_with_hits(hits):
    from hirocli.services.knowledge.agent.helpers import normalize_query

    return {"normalized_query": normalize_query("the question"), "hits": hits}


@pytest.mark.asyncio
async def test_rerank_node_noop_when_disabled(tmp_path: Path) -> None:
    prefs = WorkspacePreferences()  # reranker disabled by default
    svc = _FakeService()
    graph = _graph(svc, prefs, tmp_path)
    out = await graph.rerank_node(_state_with_hits([_hit(0, "a", 0.9)]))
    assert out == {}
    assert svc.calls == []  # service never invoked when disabled


@pytest.mark.asyncio
async def test_rerank_node_success_sets_reranked(tmp_path: Path) -> None:
    prefs = WorkspacePreferences()
    prefs.knowledge.retrieval.reranker.enabled = True
    prefs.knowledge.retrieval.reranker.model_id = "local:ms-marco-multibert-l-12"
    reranked = [_hit(2, "c", 0.1)]
    svc = _FakeService(result=reranked)
    graph = _graph(svc, prefs, tmp_path)
    out = await graph.rerank_node(_state_with_hits([_hit(0, "a", 0.9), _hit(2, "c", 0.1)]))
    assert out["reranked"] is True
    assert out["hits"] == reranked
    assert svc.calls[0]["model_id"] == "local:ms-marco-multibert-l-12"


@pytest.mark.asyncio
async def test_rerank_node_falls_back_on_error(tmp_path: Path) -> None:
    prefs = WorkspacePreferences()
    prefs.knowledge.retrieval.reranker.enabled = True
    prefs.knowledge.retrieval.reranker.model_id = "local:bge-reranker-v2-m3"
    svc = _FakeService(error=reg.RerankerNotDownloadedError("local:bge-reranker-v2-m3"))
    graph = _graph(svc, prefs, tmp_path)
    out = await graph.rerank_node(_state_with_hits([_hit(0, "a", 0.9)]))
    assert out == {}  # fallback: keep retrieval order, reranked stays falsy


@pytest.mark.asyncio
async def test_build_context_score_source_without_rerank(tmp_path: Path) -> None:
    prefs = WorkspacePreferences()  # hybrid default True
    graph = _graph(_FakeService(), prefs, tmp_path)
    state = _state_with_hits([_hit(0, "a", 0.9), _hit(1, "b", 0.1)])
    out = await graph.build_context_node(state)
    sources = out["sources"]
    assert [s.score_source for s in sources] == ["rrf", "rrf"]
    # min-max within set: top hit 1.0, lowest 0.0
    assert sources[0].relevance == 1.0
    assert sources[1].relevance == 0.0


@pytest.mark.asyncio
async def test_build_context_score_source_when_reranked(tmp_path: Path) -> None:
    prefs = WorkspacePreferences()
    graph = _graph(_FakeService(), prefs, tmp_path)
    hit = _hit(0, "a", 0.9)
    # simulate a reranked hit carrying its own normalized relevance
    from dataclasses import replace

    hit = replace(hit, rerank_score=2.0, relevance=0.88)
    state = {**_state_with_hits([hit]), "reranked": True}
    out = await graph.build_context_node(state)
    src = out["sources"][0]
    assert src.score_source == "reranker"
    assert src.relevance == 0.88
    assert src.rerank_score == 2.0
