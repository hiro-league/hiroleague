"""Characterization net for ``KnowledgeAgentGraph`` (docs §5.2).

Black-box tests over the compiled knowledge graph — both forms: the full Ask/CLI/HTTP
``build()`` (retrieve → cited answer) and the retrieval-only ``build_retrieval()`` the chat
graph nests. They pin the routing + state contract (flat leg, small-talk skip, graphiti
soft-fallback, retrieval-only stop) so the agent-graph refactor
(``docs/agent-graph-refactor-design.md``) can move code underneath them.

Placement: this lives in ``services/knowledge/`` (NOT ``services/knowledge/agent/``) — a test
collected inside the agent package corrupts ``agent.graph`` for later monkeypatch tests
(see ``reference_agent-package-test-placement`` memory).

The answering LLM is monkeypatched to "not configured" so ``call_model`` takes its deterministic
fallback path — these tests characterize graph wiring, not the answer model, and never hit a
network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import hirocli.services.knowledge.agent.answer_nodes as knowledge_answer_module
from hirocli.domain.preferences import load_preferences
from hirocli.runtime.tests.graph_fakes import (
    FakeKnowledgeService,
    RecordingLedgerSink,
    run_graph,
)
from hirocli.runtime.agent_graph.ledger import LedgerSink
from hirocli.runtime.agent_graph.services import AgentServices
from hirocli.services.knowledge.agent import KnowledgeAgentGraph, KnowledgeGraphConfig
from hirocli.services.knowledge.agent.legs import RetrievalLeg


@pytest.fixture(autouse=True)
def _no_answering_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``call_model`` down its no-LLM fallback so the answer is deterministic + offline."""
    monkeypatch.setattr(knowledge_answer_module, "resolve_knowledge_answering_llm", lambda *a, **k: None)


def _build(tmp_path: Path, *, service: Any = None, retrieval_only: bool = False):
    prefs = load_preferences(tmp_path)
    graph = KnowledgeAgentGraph(
        AgentServices(workspace_path=tmp_path, ledger_sink=LedgerSink(tmp_path))
    )
    sink = RecordingLedgerSink(tmp_path)
    graph._ledger_sink = sink  # capture flushed ledger rows
    config = KnowledgeGraphConfig(
        service=service or FakeKnowledgeService(), prefs=prefs, workspace_id=None
    )
    compiled = graph.build_retrieval(config) if retrieval_only else graph.build(config)
    return compiled, sink


def _query(**over: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "query": "what is hiro?",
        "rewrite": False,  # no rewrite LLM in characterization
        "top_k": 5,
        "min_score": 0.0,
        "filters": {},
        "inbound_id": "k-1",
        "chat_channel_id": 0,
        "character_id": "hiro",
        "user_id": "",
    }
    state.update(over)
    return state


# ---------------------------------------------------------------------------
# K1 — flat leg, results present → fallback answer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flat_leg_answers_from_sources(tmp_path: Path) -> None:
    compiled, sink = _build(tmp_path)
    result = await run_graph(compiled, _query())

    assert result.final.get("no_results") is False
    assert len(result.final.get("sources") or []) == 1
    answer = result.final.get("answer") or ""
    assert answer.startswith("Found")  # deterministic no-LLM fallback
    # Ledger labels are ``knowledge/<node>`` — the prefix groups the run in the admin
    # Graph Runs view and avoids collisions with chat-side ``call_model``/``finalize``.
    nodes = set(sink.nodes())
    assert {
        "knowledge/embed_query",
        "knowledge/vector_search",
        "knowledge/build_context",
        "knowledge/call_model",
        "knowledge/finalize",
    } <= nodes
    assert sink.decisions()["knowledge/build_context"][0] == "ok"
    assert sink.decisions()["knowledge/finalize"][0] == "completed"


# ---------------------------------------------------------------------------
# K2 — small talk (knowledge_needed=false) skips retrieval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_small_talk_skips_retrieval(tmp_path: Path) -> None:
    compiled, sink = _build(tmp_path)
    result = await run_graph(compiled, _query(knowledge_needed=False))

    assert result.final.get("no_results") is True
    assert (result.final.get("sources") or []) == []
    nodes = set(sink.nodes())
    # The skip edge bypasses the whole retrieval spine and the answer step.
    assert "knowledge/embed_query" not in nodes
    assert "knowledge/vector_search" not in nodes
    assert "knowledge/call_model" not in nodes
    assert sink.decisions()["knowledge/finalize"][0] == "empty"


# ---------------------------------------------------------------------------
# K3 — graphiti mode with no graph built → soft-fallback to the vector leg
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graphiti_mode_soft_falls_back_to_vector(tmp_path: Path) -> None:
    compiled, sink = _build(tmp_path)
    result = await run_graph(compiled, _query(graph_mode="graphiti"))

    # No graph DB in a fresh workspace → graph_expand skips and routing falls through to vector.
    assert sink.decisions()["knowledge/graph_expand"][0] == "skipped"
    nodes = set(sink.nodes())
    assert "knowledge/vector_search" in nodes
    assert "knowledge/graph_fetch" not in nodes
    assert (result.final.get("answer") or "").startswith("Found")


# ---------------------------------------------------------------------------
# K4 — retrieval-only form stops at build_context (no answer step)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieval_only_form_stops_at_build_context(tmp_path: Path) -> None:
    compiled, sink = _build(tmp_path, retrieval_only=True)
    result = await run_graph(compiled, _query())

    assert len(result.final.get("sources") or []) == 1
    assert (result.final.get("context") or "") != ""
    assert "answer" not in result.final
    nodes = set(sink.nodes())
    assert "knowledge/build_context" in nodes
    assert "knowledge/call_model" not in nodes
    assert "knowledge/finalize" not in nodes


# ---------------------------------------------------------------------------
# K5 — effective_leg is resolved once in graph_expand (P8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flat_leg_resolves_effective_leg_flat(tmp_path: Path) -> None:
    compiled, _sink = _build(tmp_path)
    result = await run_graph(compiled, _query())

    assert result.final.get("effective_leg") == RetrievalLeg.FLAT.value


@pytest.mark.asyncio
async def test_graphiti_soft_fallback_resolves_effective_leg_flat(tmp_path: Path) -> None:
    compiled, sink = _build(tmp_path)
    result = await run_graph(compiled, _query(graph_mode="graphiti"))

    assert result.final.get("effective_leg") == RetrievalLeg.FLAT.value
    nodes = set(sink.nodes())
    assert "knowledge/vector_search" in nodes
    assert "knowledge/graph_fetch" not in nodes
