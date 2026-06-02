"""Tests for Graphiti graph-object → wire DTO mapping (pure)."""

from __future__ import annotations

import datetime as dt

from hirocli.services.knowledge.graph.graphiti_serialize import edge_to_dto, node_to_dto


class _Node:
    def __init__(self, uuid, name, labels, summary="") -> None:
        self.uuid = uuid
        self.name = name
        self.labels = labels
        self.summary = summary


class _Edge:
    def __init__(self, uuid, src, tgt, name, fact, episodes, *, valid_at=None, invalid_at=None) -> None:
        self.uuid = uuid
        self.source_node_uuid = src
        self.target_node_uuid = tgt
        self.name = name
        self.fact = fact
        self.episodes = episodes
        self.valid_at = valid_at
        self.invalid_at = invalid_at


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
