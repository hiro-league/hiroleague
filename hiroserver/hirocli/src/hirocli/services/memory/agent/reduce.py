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


def _edge_distinct_key(item: AccumulatedItem) -> str:
    """Distinct-object key for an edge (Bug B): the resolved OBJECT node (the relation's target)
    identifies the thing the fact is about, so several facts about the SAME object collapse to one
    (e.g. "plans to watch Coco" + "Coco is on Disney+" → one Coco). Falls back to the normalized
    fact text when no target uuid is present (legacy/text-only rows). NOTE: this counts distinct
    relation *targets*; it does not type-filter (e.g. movies vs other objects) — a typed count is a
    separate, larger change, deliberately out of scope here."""
    target = str(item.payload.get("target_uuid") or "").strip()
    if target:
        return f"t:{target}"
    text = _edge_text(item).lower()
    return f"f:{text}" if text else ""


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


def _time_sorted_all_kinds(by_kind: dict[str, list[AccumulatedItem]]) -> list[AccumulatedItem]:
    """Edges + episodes time-sorted; entities (no timeline) trail in insertion order. Shared by the
    reduce ops that present the full recalled set so they order it identically — and so callers that
    already hold ``items_by_kind()`` need not re-fetch it (F4)."""
    return _sort_timed_items(by_kind["edge"] + by_kind["episode"]) + by_kind["entity"]


def _dedupe_and_time_sort(acc: Accumulator) -> ReducedSet:
    """Baseline presentation: dedupe is already in the accumulator; time-sort edges + episodes."""
    return ReducedSet(items=_time_sorted_all_kinds(acc.items_by_kind()), summary={"op": "none"})


def _order_by_time(acc: Accumulator) -> ReducedSet:
    return ReducedSet(items=_time_sorted_all_kinds(acc.items_by_kind()), summary={"op": "order_by_time"})


def _distinct_count(acc: Accumulator, *, kind: str) -> ReducedSet:
    """Count DISTINCT things of ``kind`` and hand the answerer the FULL recalled set.

    Three fixes vs. the original:
      • Bug A — never starve the answerer to one kind: ``items`` is the full deduped set across all
        kinds (so entities/episodes survive a ``distinct_count{kind:edge}``); the reduce ANNOTATES
        with a count, it does not replace the context.
      • Bug B — count distinct OBJECTS, not raw rows: edges dedupe by resolved object
        (``_edge_distinct_key``), entities by name; episodes are inherently distinct turns.
      • Bug C — the summary carries ``op`` so the answer prompt's computed block can render it.
    """
    target = _normalize_target_kind(kind)
    by_kind = acc.items_by_kind()  # F4: fetch once, reuse for both the count and the full set
    target_items = by_kind[target]
    summary: dict[str, Any] = {"op": "distinct_count", "kind": target}
    if target == "entity":
        names = list(dict.fromkeys(n for n in (_entity_name(i) for i in target_items) if n))
        summary["count"] = len(names)
        summary["names"] = names
    elif target == "episode":
        summary["count"] = len(target_items)  # episodes are uuid-distinct turns
    else:  # edge → distinct resolved objects
        keys = {k for k in (_edge_distinct_key(i) for i in target_items) if k}
        summary["count"] = len(keys)
    # Bug A: the answerer receives every recalled element (all kinds, time-sorted) — same set as
    # ``op:none`` — with the computed count alongside in the summary.
    return ReducedSet(items=_time_sorted_all_kinds(by_kind), summary=summary)


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
        # M3 fix: a subject/attribute was requested but NOTHING matched → there is no "latest
        # value of X" to report. Return empty instead of silently falling back to the newest
        # UNRELATED edge (which the answerer would present as the current value of X).
        if not filtered:
            return ReducedSet(items=[], summary=_latest_summary(0, subject, attribute))
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

    return ReducedSet(items=items, summary=_latest_summary(len(items), subject, attribute))


def _latest_summary(groups: int, subject: str | None, attribute: str | None) -> dict[str, Any]:
    summary: dict[str, Any] = {"op": "latest", "groups": groups}
    if subject:
        summary["subject"] = subject
    if attribute:
        summary["attribute"] = attribute
    return summary


# Words too generic to carry anchor meaning — dropped before scoring so overlap reflects the
# distinctive terms (a model anchor like "when the editing job started" matches on editing/job/start,
# not on "when"/"the").
_ANCHOR_STOPWORDS = frozenset(
    {
        "the", "a", "an", "of", "to", "and", "or", "in", "on", "at", "for", "with", "from",
        "is", "was", "were", "be", "did", "do", "does", "when", "what", "how", "long",
        "i", "my", "me", "you", "your", "it", "that", "this", "then", "than", "between",
    }
)


def _anchor_tokens(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z0-9]+", str(text or "").lower())
        if len(w) > 2 and w not in _ANCHOR_STOPWORDS
    }


def _item_anchor_tokens(item: AccumulatedItem) -> set[str]:
    tokens: set[str] = set()
    for part in (
        item.goal,
        _edge_text(item),
        str(item.payload.get("name") or ""),
        str(item.payload.get("memory") or ""),
    ):
        tokens |= _anchor_tokens(part)
    return tokens


def _find_anchor(
    acc: Accumulator, anchor: str, *, exclude_ids: set[int]
) -> AccumulatedItem | None:
    """M4 fix: pick the item with the highest fraction of the anchor's distinctive words (not the
    first literal-substring hit), tie-breaking toward the more recent item, and skipping items
    already claimed by another anchor so two anchors can't collapse onto the same fact."""
    needle = _anchor_tokens(anchor)
    if not needle:
        return None
    best: AccumulatedItem | None = None
    best_score = 0.0
    best_ts = datetime.min.replace(tzinfo=UTC)
    for kind in ("edge", "episode"):
        for item in acc.items_by_kind()[kind]:
            if id(item) in exclude_ids:
                continue
            overlap = len(needle & _item_anchor_tokens(item))
            if overlap == 0:
                continue
            score = overlap / len(needle)
            ts = _item_timestamp(item) or datetime.min.replace(tzinfo=UTC)
            if score > best_score or (score == best_score and ts > best_ts):
                best, best_score, best_ts = item, score, ts
    return best


def _date_diff(acc: Accumulator, *, anchors: list[str]) -> ReducedSet:
    matched: list[AccumulatedItem] = []
    timestamps: list[datetime] = []
    used_ids: set[int] = set()
    for anchor in anchors:
        item = _find_anchor(acc, anchor, exclude_ids=used_ids)
        if item is None:
            continue
        ts = _item_timestamp(item)
        if ts is None:
            continue
        used_ids.add(id(item))
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
