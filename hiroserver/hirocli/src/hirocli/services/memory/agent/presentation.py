"""Accumulator presentation for the memory-eval recall leg.

Was the deterministic "reduce" layer (distinct_count / order_by_time / latest / date_diff /
keep_conflicting). Reduce was removed (2026-06): across three eval traces the ops produced ~zero
clean wins and injected wrong authoritative numbers, so the agent no longer declares one. What
remains is the baseline presentation every recall used anyway — dedupe (already done in the
``Accumulator``) + time-sort — plus the row adapter to the legacy eval recall shape.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from hirocli.services.memory.agent.accumulator import AccumulatedItem, Accumulator


def present_accumulator(acc: Accumulator) -> list[AccumulatedItem]:
    """The recalled set handed to the answerer: edges + episodes time-sorted, entities (no timeline)
    trailing in insertion order. Dedupe is already done inside the ``Accumulator``."""
    by_kind = acc.items_by_kind()
    return _sort_timed_items(by_kind["edge"] + by_kind["episode"]) + by_kind["entity"]


def accumulated_item_to_recall_row(item: AccumulatedItem) -> dict[str, Any]:
    """Adapt an accumulated row to the legacy eval recall shape (answerer + judge)."""
    row = dict(item.payload)
    if not str(row.get("memory") or "").strip():
        text = (str(row.get("fact") or row.get("summary") or row.get("content") or "")).strip()
        if text:
            row["memory"] = text
    kind = str(row.get("kind") or "fact")
    if kind == "edge":
        row["kind"] = "fact"
    row["search_id"] = item.search_id
    row["goal"] = item.goal
    return row


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


__all__ = [
    "accumulated_item_to_recall_row",
    "present_accumulator",
]
