"""Accumulator presentation for the memory-eval recall leg.

Was the deterministic "reduce" layer (distinct_count / order_by_time / latest / date_diff /
keep_conflicting). Reduce was removed (2026-06): across three eval traces the ops produced ~zero
clean wins and injected wrong authoritative numbers, so the agent no longer declares one. What
remains is the baseline presentation every recall used anyway — dedupe (already done in the
``Accumulator``) + time-sort — plus the row adapter to the legacy eval recall shape.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
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


# --- Recalled-context rendering (moved here from services/eval/judge.py, P3) -----------------
# Renders recalled hits into the markdown block both the chat persona (context_assembly.memory_block)
# and the eval answer/judge prompts consume. Lives under services/memory so runtime doesn't import
# eval; eval re-exports it from ``judge`` for its own cohesion.


@dataclass(frozen=True)
class RecallRenderOptions:
    """Which per-fact temporal annotations the recalled-context renderer emits + per-kind caps.

    ``show_event_time`` → the ``as of`` label (valid_at), ``show_expired_at`` → ``until``
    (invalid_at), plus the ``SUPERSEDED`` flag. The ``stated`` date (statement/source-episode time)
    is NOT gated — it is the answer anchor for resolving relative phrasing, always shown for facts +
    messages. Caps score-rank each kind desc, keep the top ``max_elements_per_kind``, sanitize every
    element to one capped line. Defaults = the pref defaults: as-of on, until/superseded off."""

    show_event_time: bool = True
    show_expired_at: bool = False
    show_superseded: bool = False
    max_elements_per_kind: int = 30
    max_fact_chars: int = 240
    max_episode_chars: int = 300
    max_summary_chars: int = 400


# Per-kind section order + heading for the recalled-context prompt (facts → entities → messages).
_RECALL_SECTIONS: tuple[tuple[str, str], ...] = (
    ("fact", "### Relevant Facts"),
    ("entity", "### Relevant Entities"),
    ("episode", "### Relevant Messages"),
)


def _sanitize_oneline(text: Any, cap: int) -> str:
    """Collapse a recalled element's text to ONE capped line so it can't break the prompt layout:
    newlines/tabs → spaces, strip leading markdown markers (#, -, *, >, `) that would open a fake
    section or bullet, squeeze whitespace, then truncate to ``cap`` chars with an ellipsis."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    s = re.sub(r"^[#>*`\-\s]+", "", s)
    if cap > 0 and len(s) > cap:
        s = s[: cap - 1].rstrip() + "…"
    return s


def _score_of(hit: dict[str, Any]) -> float:
    """Retrieval score for ranking (desc); missing/garbage → 0.0 so it sorts last."""
    raw = hit.get("score")
    return float(raw) if isinstance(raw, (int, float)) else 0.0


def _format_recall_item(hit: dict[str, Any], render: RecallRenderOptions) -> str:
    """One recalled item → a single sanitized prompt line WITH useful metadata, but NOT the score.

    Metadata kept: relationship + temporal validity (facts), type (entities), timestamp (episodes).
    Text fields are sanitized to one capped line; ``render`` toggles which temporal annotations
    appear."""
    kind = str(hit.get("kind") or "fact")
    if kind == "entity":
        name = _sanitize_oneline(hit.get("name") or "", 120)
        etype = str(hit.get("entity_type") or "").strip()
        summary = _sanitize_oneline(
            hit.get("summary") or hit.get("memory") or "", render.max_summary_chars
        )
        head = f"{name} ({etype})" if name and etype else (name or "entity")
        return f"{head}: {summary}" if summary else head
    if kind == "episode":
        when = str(hit.get("valid_at") or "").strip()
        body = _sanitize_oneline(hit.get("memory") or "", render.max_episode_chars)
        # A message's leading [DATE] IS its statement date — the anchor for relative phrasing.
        # ALWAYS shown, independent of show_event_time.
        return f"[{when}] {body}" if when else body
    # fact (default): "[stated] fact [RELATION · as of: D · until: D]".
    fact = _sanitize_oneline(hit.get("fact") or hit.get("memory") or "", render.max_fact_chars)
    rel = str(hit.get("name") or "").strip()
    stated = str(hit.get("stated") or "").strip()
    valid_at = str(hit.get("valid_at") or "").strip()
    invalid_at = str(hit.get("invalid_at") or "").strip()
    bits: list[str] = []
    if rel:
        bits.append(rel)
    if render.show_event_time and valid_at:
        bits.append(f"as of: {valid_at}")
    if render.show_expired_at and invalid_at:
        bits.append(f"until: {invalid_at}")
    if render.show_superseded and hit.get("superseded"):
        bits.append("SUPERSEDED")
    body = f"{fact} [{' · '.join(bits)}]" if bits else fact
    # `stated` (when it was SAID) leads as a bare [DATE] timestamp — the sole anchor for relative
    # phrases — always shown, never behind a toggle.
    return f"[{stated}] {body}" if stated else body


def format_recall_context(
    hits: "list[dict[str, Any]] | None", render: RecallRenderOptions | None = None
) -> str:
    """Render recalled hits into markdown sections (Relevant Facts / Entities / Messages) — only the
    kinds that exist, each item with metadata (no score). Shared by the chat memory block and the
    eval answer + judge prompts so all see the SAME structured context. Empty ⇒ ``""`` (callers
    supply their own fallback)."""
    render = render or RecallRenderOptions()
    items = list(hits or [])
    if not items:
        return ""
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for hit in items:
        by_kind.setdefault(str(hit.get("kind") or "fact"), []).append(hit)
    sections: list[str] = []
    for kind, heading in _RECALL_SECTIONS:
        rows = by_kind.get(kind)
        if not rows:
            continue
        # Score-rank desc, then keep the top N per kind so answer-relevant elements aren't buried.
        rows = sorted(rows, key=_score_of, reverse=True)[: render.max_elements_per_kind]
        lines = "\n".join(f"- {_format_recall_item(h, render)}" for h in rows)
        sections.append(f"{heading}\n{lines}")
    return "\n\n".join(sections)


__all__ = [
    "RecallRenderOptions",
    "accumulated_item_to_recall_row",
    "format_recall_context",
    "present_accumulator",
]
