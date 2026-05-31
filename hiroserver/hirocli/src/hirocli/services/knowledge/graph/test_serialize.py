"""Tests for graph node/edge → viz DTO serialization (pure, no Ladybug)."""

from __future__ import annotations

from .serialize import edge_to_dto, node_to_dto
from .store import GraphEdge, GraphNode


def test_node_to_dto_shape() -> None:
    node = GraphNode(
        id="n1",
        name="Sara",
        type="Person",
        normalized_name="sara",
        aliases=("mom", "my mother"),
        chunk_ids=("c1", "c2"),
        document_ids=("d1",),
    )
    dto = node_to_dto(node)
    assert dto == {
        "id": "n1",
        "name": "Sara",
        "type": "Person",
        "aliases": ["mom", "my mother"],
        "chunk_ids": ["c1", "c2"],
        "document_ids": ["d1"],
    }


def test_edge_to_dto_renames_endpoints_and_carries_fact() -> None:
    edge = GraphEdge(
        id="e1",
        source_id="n1",
        target_id="n2",
        rel_type="LIVES_IN",
        chunk_ids=("c1",),
        document_ids=("d1",),
        attrs={"fact": "Sara lives in Cairo"},
    )
    dto = edge_to_dto(edge)
    # force-graph's link model expects source/target, not source_id/target_id.
    assert dto["source"] == "n1" and dto["target"] == "n2"
    assert "source_id" not in dto and "target_id" not in dto
    assert dto["rel_type"] == "LIVES_IN"
    assert dto["fact"] == "Sara lives in Cairo"
    assert dto["chunk_ids"] == ["c1"]


def test_edge_to_dto_fact_defaults_empty() -> None:
    edge = GraphEdge(id="e1", source_id="n1", target_id="n2", rel_type="KNOWS")
    assert edge_to_dto(edge)["fact"] == ""
