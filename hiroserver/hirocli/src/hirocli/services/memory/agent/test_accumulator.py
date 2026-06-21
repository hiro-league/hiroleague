"""Tests for the kind-partitioned retrieval Accumulator."""

from __future__ import annotations

from hirocli.services.memory.agent.accumulator import Accumulator


def test_dedup_within_same_kind() -> None:
    """Same (kind, uuid) seen twice → second call returns no new items."""
    acc = Accumulator()
    hit = {"kind": "fact", "uuid": "e1", "memory": "Budget is $50", "fact": "Budget is $50"}

    added_first = acc.merge([hit], search_id=1, goal="budget")
    added_second = acc.merge([hit], search_id=2, goal="retry")

    assert len(added_first) == 1
    assert added_second == []
    assert acc.size() == 1
    # Provenance stays on the first-seen copy — not overwritten by the retry call.
    item = acc.items_by_kind()["edge"][0]
    assert item.search_id == 1
    assert item.goal == "budget"


def test_separate_namespaces_per_kind() -> None:
    """Same uuid across different kinds → both stored (edge/entity/episode uuids are separate namespaces)."""
    acc = Accumulator()
    hits = [
        {"kind": "fact", "uuid": "shared", "memory": "fact text", "fact": "fact text"},
        {"kind": "entity", "uuid": "shared", "name": "Alice", "summary": "About Alice: …"},
        {"kind": "episode", "uuid": "shared", "memory": "episode body"},
    ]

    added = acc.merge(hits, search_id=1, goal="cross-kind")

    assert len(added) == 3
    assert acc.size() == 3
    by_kind = acc.items_by_kind()
    assert len(by_kind["edge"]) == 1
    assert len(by_kind["entity"]) == 1
    assert len(by_kind["episode"]) == 1


def test_provenance_recorded() -> None:
    """search_id and goal are preserved on every accumulated item."""
    acc = Accumulator()
    hits = [
        {"kind": "fact", "uuid": "e1", "memory": "f1", "fact": "f1"},
        {"kind": "entity", "uuid": "n1", "name": "Bob", "summary": "About Bob: …"},
    ]

    acc.merge(hits, search_id=7, goal="profile-lookup")

    for item in acc.items_by_kind()["edge"] + acc.items_by_kind()["entity"]:
        assert item.search_id == 7
        assert item.goal == "profile-lookup"


def test_skips_hits_without_uuid_or_text() -> None:
    """A hit with no uuid AND no memory/fact/summary text has nothing to dedup on — drop it."""
    acc = Accumulator()
    hits = [
        {"kind": "fact"},  # no uuid, no text → dropped
        {"kind": "fact", "uuid": "e1", "fact": "valid"},  # kept
    ]

    added = acc.merge(hits, search_id=1, goal="g")

    assert len(added) == 1
    assert acc.size() == 1


def test_text_fallback_when_uuid_missing() -> None:
    """Legacy text-only hits (no uuid) dedup on the memory/fact text."""
    acc = Accumulator()
    hit = {"kind": "fact", "memory": "Budget is $50"}

    first = acc.merge([hit], search_id=1, goal="g")
    second = acc.merge([dict(hit)], search_id=2, goal="g2")

    assert len(first) == 1
    assert second == []
    assert acc.size() == 1


def test_unknown_kind_normalizes_to_edge() -> None:
    """A hit with an unrecognized kind string is bucketed as edge (the safest default)."""
    acc = Accumulator()
    acc.merge([{"kind": "weird", "uuid": "x1", "memory": "?"}], search_id=1, goal="g")

    assert acc.items_by_kind()["edge"][0].uuid == "x1"
    assert acc.items_by_kind()["entity"] == []
    assert acc.items_by_kind()["episode"] == []


def test_size_and_items_by_kind_partition() -> None:
    """size() == total; items_by_kind always returns the three buckets even when some are empty."""
    acc = Accumulator()
    acc.merge(
        [
            {"kind": "fact", "uuid": "e1", "fact": "x"},
            {"kind": "fact", "uuid": "e2", "fact": "y"},
            {"kind": "entity", "uuid": "n1", "name": "A"},
        ],
        search_id=1,
        goal="g",
    )

    assert acc.size() == 3
    by_kind = acc.items_by_kind()
    assert set(by_kind.keys()) == {"edge", "entity", "episode"}
    assert len(by_kind["edge"]) == 2
    assert len(by_kind["entity"]) == 1
    assert by_kind["episode"] == []
