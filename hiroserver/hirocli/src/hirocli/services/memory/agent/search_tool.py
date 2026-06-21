"""LLM-facing ``search_memory`` operation for the agentic retrieval loop.

Follows the Tools Architecture pattern (``hirocli.tools.base.Tool``): this module owns the
operation + schema; P3 binds it into the LangGraph agent, and it can later gain CLI/HTTP
surfaces without duplicating logic. Eval-only for now — not registered on the chat agent.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from hiro_commons.log import Logger
from pydantic import BaseModel, Field, ValidationError, field_validator

from hirocli.domain.preferences import RetrievalAgentLimits
from hirocli.services.memory.agent.accumulator import AccumulatedItem, Accumulator
from hirocli.services.memory.graphiti_conversation import GraphitiConversationMemory

log = Logger.get("SVC.MEMORY.AGENT.SEARCH")

# Hard ceiling on the sub-query list, matching ``RetrievalAgentLimits.max_parallel_searches``'s
# pydantic upper bound (``le=5``). The CONFIGURED cap is enforced at runtime in ``call()`` against
# ``limits.max_parallel_searches``; this static guard just rejects absurd lists at parse time.
_MAX_SUBQUERIES_HARD = 5


class SearchMemoryQuery(BaseModel):
    """One sub-query inside a ``search_memory`` call (P9: multi-arg tool).

    A turn carries 1..N of these in ``SearchMemoryArgs.queries``; the tool runs them
    concurrently. Each gets its own knobs + ``goal`` provenance label."""

    query: str
    temporal: Literal["current", "all"] = "current"
    limit: int = 20
    hops: Literal[1, 2, 3] = 1
    show_expiry: bool = False
    goal: str = ""

    @field_validator("query", mode="before")
    @classmethod
    def _strip_query(cls, value: str) -> str:
        return str(value or "").strip()


class SearchMemoryArgs(BaseModel):
    """The single ``search_memory`` tool call per turn — a list of sub-queries.

    The model emits ONE tool call whose ``queries`` list holds the decomposition (P9): no
    reliance on the model supporting parallel TOOL CALLS, which is uneven across the fleet."""

    queries: list[SearchMemoryQuery] = Field(..., min_length=1, max_length=_MAX_SUBQUERIES_HARD)


class SearchMemorySubResult(BaseModel):
    """Result of one sub-query — carries its knobs back for the trace + UI (P8)."""

    sid: int
    goal: str
    query: str
    temporal: str
    limit: int
    hops: int
    show_expiry: bool
    returned: int
    new: int
    items: list[dict[str, Any]]
    error: str | None = None


class SearchMemoryResult(BaseModel):
    sub_results: list[SearchMemorySubResult]
    accumulated_total: int


def _preview(query: str, *, max_len: int = 60) -> str:
    text = (query or "").replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _serialize_item(item: AccumulatedItem) -> dict[str, Any]:
    """Shape one accumulated row for the agent (design §5.5)."""
    payload = item.payload
    score = payload.get("score")
    score_out = float(score) if isinstance(score, (int, float)) else None

    if item.kind == "edge":
        row: dict[str, Any] = {
            "kind": "edge",
            "id": item.uuid,
            "fact": (payload.get("fact") or payload.get("memory") or "").strip(),
            "score": score_out,
        }
        chunk_id = str(payload.get("chunk_id") or "").strip()
        if chunk_id:
            row["source_episode"] = chunk_id
        if "valid_at" in payload:
            row["valid_at"] = payload.get("valid_at") or None
        if "invalid_at" in payload:
            row["invalid_at"] = payload.get("invalid_at") or None
        if "superseded" in payload:
            row["superseded"] = bool(payload.get("superseded"))
        return row

    if item.kind == "entity":
        name = str(payload.get("name") or "").strip()
        summary = str(payload.get("summary") or payload.get("memory") or "").strip()
        if summary.startswith(f"About {name}:"):
            summary = summary[len(f"About {name}:") :].strip()
        return {
            "kind": "entity",
            "id": item.uuid,
            "name": name,
            "summary": summary,
            "score": score_out,
        }

    text = str(payload.get("memory") or payload.get("content") or "").strip()
    row = {
        "kind": "episode",
        "id": item.uuid,
        "text": text,
        "score": score_out,
    }
    valid_at = payload.get("valid_at")
    if valid_at:
        row["valid_at"] = valid_at
    return row


class SearchMemoryTool:
    """Thin clamp + concurrent dispatcher over :class:`GraphitiConversationMemory`.

    The accumulator and the flat ``search_id`` counter are injected/owned here so concurrent
    retrieval agents do not share state (P3 executor owns the accumulator). Each sub-query gets
    a globally-monotonic ``sid`` (the UI keys its Facts-tab highlight on it — kept a flat int,
    not a (turn, sub) tuple, so that join needs no change).
    """

    name = "search_memory"

    def __init__(
        self,
        *,
        memory: GraphitiConversationMemory,
        accumulator: Accumulator,
        limits: RetrievalAgentLimits,
        user_id: int,
        character_id: str,
    ) -> None:
        self._memory = memory
        self._accumulator = accumulator
        self._limits = limits
        self._user_id = user_id
        self._character_id = character_id
        self._next_search_id = 1

    async def _run_one(self, *, sid: int, q: SearchMemoryQuery) -> SearchMemorySubResult:
        """Run one sub-query. Never raises — a failure becomes an ``error`` sub-result so a
        single bad sub-query does not abort the rest of the batch (gather stays clean)."""
        # ``hops`` is soft-capped to the admin ``hops_max`` (like ``limit`` clamping) rather
        # than erroring — friendlier to the model and removes an error path.
        clamped_limit = max(self._limits.limit_min, min(self._limits.limit_max, q.limit))
        eff_hops = min(q.hops, self._limits.hops_max)
        if clamped_limit != q.limit or eff_hops != q.hops:
            log.debug(
                "search_memory clamped · sid=%d · limit %d→%d · hops %d→%d",
                sid,
                q.limit,
                clamped_limit,
                q.hops,
                eff_hops,
            )

        base = dict(
            sid=sid,
            goal=q.goal,
            query=q.query,
            temporal=q.temporal,
            limit=clamped_limit,
            hops=eff_hops,
            show_expiry=q.show_expiry,
        )

        if not q.query:
            return SearchMemorySubResult(returned=0, new=0, items=[], **base)

        try:
            hits = await self._memory.search(
                q.query,
                user_id=self._user_id,
                character_id=self._character_id,
                limit=clamped_limit,
                temporal=q.temporal,
                k_hop=eff_hops,
                show_expiry=q.show_expiry,
            )
        except Exception as exc:
            log.exception("❌ search_memory sub-query failed · sid=%d", sid)
            return SearchMemorySubResult(returned=0, new=0, items=[], error=str(exc), **base)

        added = self._accumulator.merge(hits, search_id=sid, goal=q.goal)
        return SearchMemorySubResult(
            returned=len(hits),
            new=len(added),
            items=[_serialize_item(item) for item in added],
            **base,
        )

    async def call(self, args: SearchMemoryArgs) -> SearchMemoryResult:
        # Enforce the CONFIGURED parallel cap (the static pydantic max_length is just the hard
        # ceiling). Raising here surfaces as a tool-error the model can correct next turn.
        if len(args.queries) > self._limits.max_parallel_searches:
            raise ValueError(
                f"too many sub-queries: {len(args.queries)} > max_parallel_searches "
                f"({self._limits.max_parallel_searches}); split across turns"
            )

        # Assign global sids deterministically BEFORE the concurrent dispatch (gather order is
        # nondeterministic; sid assignment must not be).
        indexed: list[tuple[int, SearchMemoryQuery]] = []
        for q in args.queries:
            sid = self._next_search_id
            self._next_search_id += 1
            indexed.append((sid, q))

        log.info(
            "⬇️ search_memory — agent · sub_queries=%d · q0='%s'",
            len(indexed),
            _preview(indexed[0][1].query) if indexed else "",
        )

        sub_results = await asyncio.gather(*[self._run_one(sid=sid, q=q) for sid, q in indexed])
        return SearchMemoryResult(
            sub_results=list(sub_results),
            accumulated_total=self._accumulator.size(),
        )


__all__ = [
    "SearchMemoryArgs",
    "SearchMemoryQuery",
    "SearchMemoryResult",
    "SearchMemorySubResult",
    "SearchMemoryTool",
    "ValidationError",
]
