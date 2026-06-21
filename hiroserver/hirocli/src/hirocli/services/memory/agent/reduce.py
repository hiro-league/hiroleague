"""Deterministic reduce primitives over an :class:`Accumulator` (design §6.1, P4).

The retrieval agent declares ``reduce.op`` on its final turn; the caller runs
``apply_reduce`` before handing facts to the answerer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from hirocli.services.memory.agent.accumulator import AccumulatedItem, Accumulator

ReduceOp = Literal[
    "none",
    "distinct_count",
    "order_by_time",
    "latest",
    "date_diff",
    "keep_conflicting",
]

_NEGATION_RE = re.compile(
    r"\b(never|not|no longer|doesn't|does not|didn't|did not|cannot|can't|won't|"
    r"without|none|nothing)\b",
    re.IGNORECASE,
)


@dataclass
class ReducedSet:
    """What goes to the answerer in place of the raw accumulator."""

    items: list[AccumulatedItem]
    summary: dict[str, Any]


def apply_reduce(acc: Accumulator, *, op: str, args: dict[str, Any] | None = None) -> ReducedSet:
    """Dispatch a model-declared reduce op over ``acc``."""
    normalized = str(op or "none").strip() or "none"
    payload = dict(args or {})

    if normalized == "none":
        return _dedupe_and_time_sort(acc)
    if normalized == "distinct_count":
        return _distinct_count(acc, kind=str(payload.get("kind") or "edge"))
    if normalized == "order_by_time":
        return _order_by_time(acc)
    if normalized == "latest":
        return _latest(
            acc,
            subject=_optional_str(payload.get("subject")),
            attribute=_optional_str(payload.get("attribute")),
        )
    if normalized == "date_diff":
        anchors = payload.get("anchors")
        if not isinstance(anchors, list):
            raise ValueError("date_diff requires anchors: list[str]")
        return _date_diff(acc, anchors=[str(a) for a in anchors])
    if normalized == "keep_conflicting":
        return _keep_conflicting(acc)
    raise ValueError(f"unknown reduce op: {normalized!r}")


def accumulated_item_to_recall_row(item: AccumulatedItem) -> dict[str, Any]:
    """Adapt an accumulated row to the legacy eval recall shape (answerer + judge)."""
    row = dict(item.payload)
    if not str(row.get("memory") or "").strip():
        text = (
            str(row.get("fact") or row.get("summary") or row.get("content") or "")
        ).strip()
        if text:
            row["memory"] = text
    kind = str(row.get("kind") or "fact")
    if kind == "edge":
        row["kind"] = "fact"
    row["search_id"] = item.search_id
    row["goal"] = item.goal
    return row


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_target_kind(kind: str) -> str:
    raw = str(kind or "edge").strip().lower()
    if raw in ("fact", "edge"):
        return "edge"
    if raw in ("entity", "episode"):
        return raw
    return "edge"


def _edge_text(item: AccumulatedItem) -> str:
    payload = item.payload
    return str(payload.get("fact") or payload.get("memory") or "").strip()


def _entity_name(item: AccumulatedItem) -> str:
    payload = item.payload
    return str(payload.get("name") or payload.get("memory") or "").strip()


def _parse_timestamp(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        pass
    for fmt in ("%Y-%m", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _item_timestamp(item: AccumulatedItem) -> datetime | None:
    payload = item.payload
    for key in ("valid_at", "stated", "timestamp"):
        ts = _parse_timestamp(payload.get(key))
        if ts is not None:
            return ts
    return None


def _sort_timed_items(items: list[AccumulatedItem]) -> list[AccumulatedItem]:
    timed = [item for item in items if _item_timestamp(item) is not None]
    untimed = [item for item in items if _item_timestamp(item) is None]
    timed.sort(key=lambda item: _item_timestamp(item) or datetime.min.replace(tzinfo=UTC))
    return timed + untimed


def _dedupe_and_time_sort(acc: Accumulator) -> ReducedSet:
    """Baseline presentation: dedupe is already in the accumulator; time-sort edges + episodes."""
    by_kind = acc.items_by_kind()
    timed_block = _sort_timed_items(by_kind["edge"] + by_kind["episode"])
    items = timed_block + by_kind["entity"]
    return ReducedSet(items=items, summary={"op": "none"})


def _order_by_time(acc: Accumulator) -> ReducedSet:
    by_kind = acc.items_by_kind()
    items = _sort_timed_items(by_kind["edge"] + by_kind["episode"]) + by_kind["entity"]
    return ReducedSet(items=items, summary={"op": "order_by_time"})


def _distinct_count(acc: Accumulator, *, kind: str) -> ReducedSet:
    target = _normalize_target_kind(kind)
    items = list(acc.items_by_kind()[target])
    if target == "entity":
        labels = [_entity_name(item) for item in items if _entity_name(item)]
        unique = list(dict.fromkeys(labels))
        summary = {"count": len(unique), "names": unique, "kind": target}
    else:
        summary = {"count": len(items), "kind": target}
    return ReducedSet(items=items, summary=summary)


def _latest(
    acc: Accumulator,
    *,
    subject: str | None,
    attribute: str | None,
) -> ReducedSet:
    edges = acc.items_by_kind()["edge"]
    if not edges:
        return ReducedSet(items=[], summary={"op": "latest"})

    needles = [n.lower() for n in (subject, attribute) if n]
    candidates = edges
    if needles:
        filtered: list[AccumulatedItem] = []
        for item in edges:
            haystack = " ".join(
                [
                    _edge_text(item),
                    str(item.payload.get("name") or ""),
                    item.goal,
                ]
            ).lower()
            if all(needle in haystack for needle in needles):
                filtered.append(item)
        if filtered:
            candidates = filtered

    if subject or attribute:
        best = max(
            candidates,
            key=lambda item: _item_timestamp(item) or datetime.min.replace(tzinfo=UTC),
        )
        items = [best]
    else:
        grouped: dict[str, AccumulatedItem] = {}
        for item in candidates:
            rel = str(item.payload.get("name") or "").strip() or _edge_text(item).split(".", 1)[0]
            existing = grouped.get(rel)
            if existing is None:
                grouped[rel] = item
                continue
            if (_item_timestamp(item) or datetime.min.replace(tzinfo=UTC)) >= (
                _item_timestamp(existing) or datetime.min.replace(tzinfo=UTC)
            ):
                grouped[rel] = item
        items = list(grouped.values())
        items.sort(
            key=lambda item: _item_timestamp(item) or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )

    summary: dict[str, Any] = {"op": "latest", "groups": len(items)}
    if subject:
        summary["subject"] = subject
    if attribute:
        summary["attribute"] = attribute
    return ReducedSet(items=items, summary=summary)


def _match_anchor(item: AccumulatedItem, anchor: str) -> bool:
    needle = anchor.strip().lower()
    if not needle:
        return False
    haystacks = [
        item.goal,
        _edge_text(item),
        str(item.payload.get("name") or ""),
        str(item.payload.get("memory") or ""),
    ]
    return any(needle in str(h).lower() for h in haystacks if h)


def _find_anchor(acc: Accumulator, anchor: str) -> AccumulatedItem | None:
    for kind in ("edge", "episode"):
        for item in acc.items_by_kind()[kind]:
            if _match_anchor(item, anchor):
                return item
    return None


def _date_diff(acc: Accumulator, *, anchors: list[str]) -> ReducedSet:
    matched: list[AccumulatedItem] = []
    timestamps: list[datetime] = []
    for anchor in anchors:
        item = _find_anchor(acc, anchor)
        if item is None:
            continue
        ts = _item_timestamp(item)
        if ts is None:
            continue
        matched.append(item)
        timestamps.append(ts)

    summary: dict[str, Any] = {"op": "date_diff", "anchors": anchors}
    if len(timestamps) >= 2:
        timestamps.sort()
        summary["days"] = (timestamps[-1] - timestamps[0]).days
    else:
        summary["days"] = None

    return ReducedSet(items=matched, summary=summary)


def _is_negating(text: str) -> bool:
    return bool(_NEGATION_RE.search(text))


def _keep_conflicting(acc: Accumulator) -> ReducedSet:
    edges = acc.items_by_kind()["edge"]
    affirming: list[AccumulatedItem] = []
    negating: list[AccumulatedItem] = []
    for item in edges:
        if _is_negating(_edge_text(item)):
            negating.append(item)
        else:
            affirming.append(item)
    return ReducedSet(
        items=affirming + negating,
        summary={
            "op": "keep_conflicting",
            "affirming": len(affirming),
            "negating": len(negating),
        },
    )


__all__ = [
    "ReducedSet",
    "ReduceOp",
    "accumulated_item_to_recall_row",
    "apply_reduce",
]
