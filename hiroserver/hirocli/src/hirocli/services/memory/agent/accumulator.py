"""Kind-partitioned accumulator for the agentic memory-retrieval loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Sequence

Kind = Literal["edge", "entity", "episode"]


@dataclass
class AccumulatedItem:
    kind: Kind
    uuid: str
    payload: dict[str, Any]
    search_id: int
    goal: str


def _normalize_kind(raw: str) -> Kind:
    """Map memory-search row kinds to the agent-facing vocabulary (fact → edge)."""
    if raw in ("fact", "edge"):
        return "edge"
    if raw == "entity":
        return "entity"
    if raw == "episode":
        return "episode"
    return "edge"


def _kind_uuid(hit: dict[str, Any]) -> tuple[Kind, str]:
    kind = _normalize_kind(str(hit.get("kind") or "fact"))
    uuid = str(hit.get("uuid") or "").strip()
    if not uuid:
        # Legacy/text-only hits lack uuids — fall back to memory text for dedup.
        uuid = str(hit.get("memory") or hit.get("fact") or hit.get("summary") or "").strip()
    return kind, uuid


class Accumulator:
    """Kind-partitioned dedup-by-uuid store.

    Edge, entity, and episode uuids are separate namespaces. Items keep provenance
    (search_id, goal) for the trace and reduce library (P4).
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], AccumulatedItem] = {}

    def merge(self, hits: Sequence[dict[str, Any]], *, search_id: int, goal: str) -> list[AccumulatedItem]:
        added: list[AccumulatedItem] = []
        for hit in hits:
            kind, uuid = _kind_uuid(hit)
            if not uuid:
                continue
            key = (kind, uuid)
            if key in self._by_key:
                continue
            item = AccumulatedItem(
                kind=kind,
                uuid=uuid,
                payload=dict(hit),
                search_id=search_id,
                goal=goal,
            )
            self._by_key[key] = item
            added.append(item)
        return added

    def size(self) -> int:
        return len(self._by_key)

    def items_by_kind(self) -> dict[str, list[AccumulatedItem]]:
        out: dict[str, list[AccumulatedItem]] = {"edge": [], "entity": [], "episode": []}
        for item in self._by_key.values():
            out[item.kind].append(item)
        return out


__all__ = ["AccumulatedItem", "Accumulator", "Kind"]
