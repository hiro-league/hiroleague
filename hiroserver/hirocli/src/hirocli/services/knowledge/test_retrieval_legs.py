"""P8 — retrieval leg helpers and routing contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.domain.preferences import load_preferences
from hirocli.runtime.tests.graph_fakes import FakeKnowledgeService, run_graph
from hirocli.services.knowledge.agent.graph import KnowledgeAgentGraph
from hirocli.services.knowledge.agent.legs import (
    RetrievalLeg,
    effective_leg,
    graphiti_facts_block,
    intended_leg,
)

K = "knowledge/"


# ---------------------------------------------------------------------------
# intended_leg
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("graph_mode", "expected"),
    [
        ("graphiti", RetrievalLeg.GRAPHITI),
        ("off", RetrievalLeg.FLAT),
        (None, RetrievalLeg.FLAT),
        ("bogus", RetrievalLeg.FLAT),
    ],
)
def test_intended_leg(graph_mode: str | None, expected: RetrievalLeg) -> None:
    assert intended_leg(graph_mode) is expected


# ---------------------------------------------------------------------------
# effective_leg (soft-fallback)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("intended", "chunk_ids", "expected"),
    [
        (RetrievalLeg.GRAPHITI, ["c1"], RetrievalLeg.GRAPHITI),
        (RetrievalLeg.GRAPHITI, [], RetrievalLeg.FLAT),
        (RetrievalLeg.FLAT, ["c1"], RetrievalLeg.FLAT),
        (RetrievalLeg.FLAT, [], RetrievalLeg.FLAT),
    ],
)
def test_effective_leg(
    intended: RetrievalLeg, chunk_ids: list[str], expected: RetrievalLeg
) -> None:
    assert effective_leg(intended, chunk_ids=chunk_ids) is expected


# ---------------------------------------------------------------------------
# graphiti_facts_block
# ---------------------------------------------------------------------------


def test_graphiti_facts_block_empty() -> None:
    assert graphiti_facts_block([]) == ""
    assert graphiti_facts_block(["", "  "]) == ""


def test_graphiti_facts_block_bulleted() -> None:
    block = graphiti_facts_block(["Adam lived in Eden", "Eve was created"])
    assert block == (
        "Known facts from the knowledge graph:\n"
        "- Adam lived in Eden\n"
        "- Eve was created"
    )


# ---------------------------------------------------------------------------
# _route_after_expand reads effective_leg
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("effective", "expected_route"),
    [
        (RetrievalLeg.GRAPHITI.value, "graph_only"),
        (RetrievalLeg.FLAT.value, "vector"),
        (None, "vector"),
    ],
)
def test_route_after_expand_reads_effective_leg(
    effective: str | None, expected_route: str
) -> None:
    state: dict = {"effective_leg": effective} if effective is not None else {}
    assert KnowledgeAgentGraph._route_after_expand(state) == expected_route  # noqa: SLF001


# ---------------------------------------------------------------------------
# Characterization extensions — effective_leg on end-to-end paths
# ---------------------------------------------------------------------------


def _build(tmp_path: Path):
    prefs = load_preferences(tmp_path)
    graph = KnowledgeAgentGraph(
        workspace_path=tmp_path,
        service=FakeKnowledgeService(),
        prefs=prefs,
        workspace_id=None,
    )
    return graph.build_retrieval()


def _query(**over):
    state = {
        "query": "what is hiro?",
        "rewrite": False,
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


@pytest.mark.asyncio
async def test_flat_leg_sets_effective_leg_flat(tmp_path: Path) -> None:
    compiled = _build(tmp_path)
    result = await run_graph(compiled, _query())

    assert result.final.get("effective_leg") == RetrievalLeg.FLAT.value
    assert len(result.final.get("sources") or []) == 1


@pytest.mark.asyncio
async def test_graphiti_soft_fallback_sets_effective_leg_flat(tmp_path: Path) -> None:
    compiled = _build(tmp_path)
    result = await run_graph(compiled, _query(graph_mode="graphiti"))

    # No graph DB → graph_expand skips → effective_leg=FLAT → vector path.
    assert result.final.get("effective_leg") == RetrievalLeg.FLAT.value
    assert len(result.final.get("sources") or []) == 1
