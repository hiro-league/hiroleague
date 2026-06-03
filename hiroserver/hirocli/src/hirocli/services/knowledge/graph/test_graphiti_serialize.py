"""Tests for Graphiti graph-object → wire DTO mapping (pure)."""

from __future__ import annotations

import datetime as dt

from hirocli.services.knowledge.graph.graphiti_serialize import (
    build_graph_dtos,
    edge_to_dto,
    node_to_dto,
)


class _Node:
    def __init__(self, uuid, name, labels, summary="", attributes=None) -> None:
        self.uuid = uuid
        self.name = name
        self.labels = labels
        self.summary = summary
        self.attributes = attributes


class _Edge:
    def __init__(
        self,
        uuid,
        src,
        tgt,
        name,
        fact,
        episodes,
        *,
        valid_at=None,
        invalid_at=None,
        expired_at=None,
    ) -> None:
        self.uuid = uuid
        self.source_node_uuid = src
        self.target_node_uuid = tgt
        self.name = name
        self.fact = fact
        self.episodes = episodes
        self.valid_at = valid_at
        self.invalid_at = invalid_at
        self.expired_at = expired_at


def test_node_to_dto_picks_ontology_type() -> None:
    dto = node_to_dto(_Node("n1", "Adam", ["Entity", "Person"], "a man"))
    assert dto["id"] == "n1"
    assert dto["name"] == "Adam"
    assert dto["type"] == "Person"  # first non-base label
    assert dto["summary"] == "a man"
    assert dto["aliases"] == []
    assert dto["chunk_ids"] == []


def test_node_to_dto_defaults_entity_when_only_base() -> None:
    assert node_to_dto(_Node("n2", "X", ["Entity"]))["type"] == "Entity"


def test_node_to_dto_tolerates_missing_attrs() -> None:
    dto = node_to_dto(object())
    assert dto["id"] == ""
    assert dto["name"] == ""
    assert dto["type"] == "Entity"


def test_edge_to_dto_maps_fact_episodes_and_temporal() -> None:
    e = _Edge(
        "e1",
        "n1",
        "n2",
        "LIVES_IN",
        "Adam lives in Cambridge",
        ["c1", "c2"],
        valid_at=dt.datetime(2024, 5, 1, tzinfo=dt.UTC),
    )
    dto = edge_to_dto(e)
    assert dto["id"] == "e1"
    assert dto["source"] == "n1"
    assert dto["target"] == "n2"
    assert dto["rel_type"] == "LIVES_IN"
    assert dto["fact"] == "Adam lives in Cambridge"
    assert dto["chunk_ids"] == ["c1", "c2"]  # episodes == point_ids
    assert dto["valid_at"] == "2024-05-01T00:00:00+00:00"
    assert dto["invalid_at"] is None


def test_edge_to_dto_filters_empty_episodes() -> None:
    dto = edge_to_dto(_Edge("e2", "a", "b", "R", "f", ["c1", "", None]))
    assert dto["chunk_ids"] == ["c1"]


def test_edge_to_dto_surfaces_expired_at() -> None:
    # A superseded fact carries expired_at → the viz can mark it retired (§5.6).
    e = _Edge(
        "e3", "n1", "n2", "LIVES_IN", "Adam lives in Boston", ["c1"],
        valid_at=dt.datetime(2024, 1, 1, tzinfo=dt.UTC),
        invalid_at=dt.datetime(2024, 5, 1, tzinfo=dt.UTC),
        expired_at=dt.datetime(2024, 5, 2, tzinfo=dt.UTC),
    )
    dto = edge_to_dto(e)
    assert dto["expired_at"] == "2024-05-02T00:00:00+00:00"


def test_node_to_dto_reads_aliases_from_attributes() -> None:
    n = _Node("n1", "Adam", ["Entity", "Person"], attributes={"aliases": ["Adam Smith", "A."]})
    assert node_to_dto(n)["aliases"] == ["Adam Smith", "A."]


def test_build_graph_dtos_derives_node_provenance_from_edges() -> None:
    # Nodes don't carry episodes — chunk_ids come from the edges touching them, and
    # document_ids map those chunks through the chunk→document map.
    nodes = [_Node("n1", "Adam", ["Entity", "Person"]), _Node("n2", "Boston", ["Entity", "Place"])]
    edges = [_Edge("e1", "n1", "n2", "LIVES_IN", "Adam lives in Boston", ["c1", "c2"])]
    out = build_graph_dtos(nodes, edges, chunk_to_document={"c1": "doc_a", "c2": "doc_a"})

    by_id = {n["id"]: n for n in out["nodes"]}
    assert by_id["n1"]["chunk_ids"] == ["c1", "c2"]
    assert by_id["n1"]["document_ids"] == ["doc_a"]  # deduped
    assert by_id["n2"]["chunk_ids"] == ["c1", "c2"]
    assert out["edges"][0]["document_ids"] == ["doc_a"]


def test_build_graph_dtos_without_map_leaves_document_ids_empty() -> None:
    nodes = [_Node("n1", "Adam", ["Entity"])]
    edges = [_Edge("e1", "n1", "n2", "R", "f", ["c1"])]
    out = build_graph_dtos(nodes, edges)
    assert out["nodes"][0]["chunk_ids"] == ["c1"]
    assert out["nodes"][0]["document_ids"] == []
