"""Tests for the memory-retrieval reduce library (P4)."""

from __future__ import annotations

import pytest

from hirocli.services.memory.agent.accumulator import AccumulatedItem, Accumulator
from hirocli.services.memory.agent.reduce import apply_reduce


def _edge(
    uuid: str,
    *,
    fact: str,
    valid_at: str,
    invalid_at: str | None = None,
    superseded: bool = False,
    name: str = "",
    goal: str = "",
) -> dict:
    row: dict = {
        "kind": "fact",
        "uuid": uuid,
        "memory": fact,
        "fact": fact,
        "valid_at": valid_at,
        "superseded": superseded,
    }
    if invalid_at is not None:
        row["invalid_at"] = invalid_at
    if name:
        row["name"] = name
    if goal:
        row["goal"] = goal
    return row


def _entity(uuid: str, *, name: str, summary: str = "") -> dict:
    return {
        "kind": "entity",
        "uuid": uuid,
        "name": name,
        "summary": summary or f"About {name}",
        "memory": summary or f"About {name}",
    }


def _episode(uuid: str, *, text: str, valid_at: str) -> dict:
    return {
        "kind": "episode",
        "uuid": uuid,
        "memory": text,
        "valid_at": valid_at,
    }


def _load(acc: Accumulator, hits: list[dict], *, sid: int = 1, goal: str = "") -> None:
    acc.merge(hits, search_id=sid, goal=goal)


def test_distinct_count_counts_only_named_kind() -> None:
    acc = Accumulator()
    _load(acc, [_edge(f"e{i}", fact=f"fact {i}", valid_at="2024-01-01") for i in range(5)])
    _load(
        acc,
        [
            _entity("n1", name="Alice"),
            _entity("n2", name="Bob"),
        ],
        sid=2,
    )

    reduced = apply_reduce(acc, op="distinct_count", args={"kind": "entity"})

    assert reduced.summary["count"] == 2
    assert reduced.summary["names"] == ["Alice", "Bob"]
    assert len(reduced.items) == 2
    assert all(item.kind == "entity" for item in reduced.items)


def test_order_by_time_sorts_edges_and_episodes_skipping_entities() -> None:
    acc = Accumulator()
    _load(
        acc,
        [
            _edge("e1", fact="middle", valid_at="2024-02-01"),
            _edge("e2", fact="latest", valid_at="2024-03-01"),
            _episode("ep1", text="early episode", valid_at="2024-01-01"),
            _entity("n1", name="Crystal"),
        ],
    )

    reduced = apply_reduce(acc, op="order_by_time")

    kinds_and_dates = [
        (item.kind, item.payload.get("valid_at")) for item in reduced.items if item.kind != "entity"
    ]
    assert kinds_and_dates == [
        ("episode", "2024-01-01"),
        ("edge", "2024-02-01"),
        ("edge", "2024-03-01"),
    ]
    assert reduced.items[-1].kind == "entity"


def test_latest_picks_newest_valid_at_per_subject_attribute() -> None:
    acc = Accumulator()
    _load(
        acc,
        [
            _edge("e1", fact="Monthly book budget is $40", valid_at="2024-01-05"),
            _edge("e2", fact="Monthly book budget is $50", valid_at="2024-02-10"),
            _edge("e3", fact="Monthly book budget is $45", valid_at="2024-01-20"),
            _edge("e4", fact="Unrelated travel plan", valid_at="2024-03-01"),
        ],
    )

    reduced = apply_reduce(
        acc,
        op="latest",
        args={"subject": "book", "attribute": "budget"},
    )

    assert len(reduced.items) == 1
    assert " $50" in _edge_text(reduced.items[0])


def test_latest_returns_empty_when_subject_attribute_match_nothing() -> None:
    """M3 fix: a subject/attribute that matches NO edge must yield an empty result, not the newest
    unrelated edge (which the answerer would otherwise present as the current value of X)."""
    acc = Accumulator()
    _load(
        acc,
        [
            _edge("e1", fact="Moved to Berlin", valid_at="2024-05-01"),
            _edge("e2", fact="Adopted a cat", valid_at="2024-06-01"),
        ],
    )

    reduced = apply_reduce(acc, op="latest", args={"subject": "phone", "attribute": "number"})

    assert reduced.items == []
    assert reduced.summary["op"] == "latest"
    assert reduced.summary["groups"] == 0


def test_date_diff_matches_free_text_anchors_by_word_overlap() -> None:
    """M4 fix: anchors match by distinctive-word overlap (not exact substring), pick the BEST match,
    and two anchors can't collapse onto the same fact."""
    acc = Accumulator()
    _load(acc, [_edge("e1", fact="Crystal started her editing job", valid_at="2024-01-01")])
    _load(acc, [_edge("e2", fact="The reading challenge deadline passed", valid_at="2024-01-15")])
    # Distractor sharing a word with anchor 1 ("job") but the wrong event.
    _load(acc, [_edge("e3", fact="Applied for a new job listing", valid_at="2024-03-01")])

    reduced = apply_reduce(
        acc,
        op="date_diff",
        args={"anchors": ["when she started the editing job", "the reading deadline"]},
    )

    # Anchor 1 best-matches e1 (editing+job+started) over e3 (only job); anchor 2 → e2.
    assert reduced.summary["days"] == 14
    assert {item.payload["uuid"] for item in reduced.items} == {"e1", "e2"}


def test_date_diff_two_named_anchors() -> None:
    acc = Accumulator()
    _load(
        acc,
        [
            _edge(
                "e1",
                fact="Editing job started on Jan 1",
                valid_at="2024-01-01",
            ),
        ],
        sid=1,
        goal="editing job start date",
    )
    _load(
        acc,
        [
            _edge(
                "e2",
                fact="Reading deadline is Jan 15",
                valid_at="2024-01-15",
            ),
        ],
        sid=2,
        goal="reading deadline",
    )

    reduced = apply_reduce(
        acc,
        op="date_diff",
        args={"anchors": ["editing job start date", "reading deadline"]},
    )

    assert reduced.summary["days"] == 14
    assert len(reduced.items) == 2


def test_keep_conflicting_partitions_affirming_vs_negating() -> None:
    acc = Accumulator()
    _load(
        acc,
        [
            _edge("e1", fact="User has visited Paris", valid_at="2024-01-01"),
            _edge("e2", fact="User has never visited Paris", valid_at="2024-02-01"),
        ],
    )

    reduced = apply_reduce(acc, op="keep_conflicting")

    assert reduced.summary["affirming"] == 1
    assert reduced.summary["negating"] == 1
    assert "never" in reduced.items[1].payload["fact"].lower()


def test_apply_reduce_unknown_op_raises() -> None:
    with pytest.raises(ValueError, match="unknown reduce op"):
        apply_reduce(Accumulator(), op="compare")


def test_op_none_is_dedupe_plus_time_sort() -> None:
    acc = Accumulator()
    _load(
        acc,
        [
            _edge("e2", fact="later", valid_at="2024-02-01"),
            _edge("e1", fact="earlier", valid_at="2024-01-01"),
        ],
    )

    reduced = apply_reduce(acc, op="none")

    assert [item.uuid for item in reduced.items] == ["e1", "e2"]
    assert reduced.summary["op"] == "none"


def _edge_text(item: AccumulatedItem) -> str:
    payload = item.payload
    return str(payload.get("fact") or payload.get("memory") or "")
