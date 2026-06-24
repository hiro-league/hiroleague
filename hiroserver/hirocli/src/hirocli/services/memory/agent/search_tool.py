"""LLM-facing ``search_memory`` operation for the agentic retrieval loop.

Follows the Tools Architecture pattern (``hirocli.tools.base.Tool``): this module owns the
operation + schema; P3 binds it into the LangGraph agent, and it can later gain CLI/HTTP
surfaces without duplicating logic. Eval-only for now — not registered on the chat agent.
"""

from __future__ import annotations

import asyncio
import re
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
    # M1 fix: ``None`` means "model omitted limit" → resolve to the admin pref ``limit_default``
    # in ``_run_one`` (was a hardcoded ``20`` that shadowed the editable pref, making it inert).
    limit: int | None = None
    # Numeric bound (ge/le) instead of ``Literal[1, 2, 3]``: an integer Literal becomes a JSON-schema
    # integer ``enum``, which langchain_google_genai converts to a genai ``Schema`` whose ``enum`` is
    # typed ``list[str]`` — so a Gemini retrieval model 400s with "Input should be a valid string"
    # (3 errors, one per enum value). ``ge``/``le`` render as ``minimum``/``maximum`` (provider-safe),
    # and ``hops`` is soft-clamped to ``hops_max`` at runtime anyway, so the strict enum isn't needed.
    hops: int = Field(default=1, ge=1, le=3)
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
        # Fidelity fix (items 1,3,5): surface the relation name and the `stated` (said) date to the
        # agent — both live in the accumulated row but were dropped here, leaving the agent unable to
        # tell e.g. PLANS_TO_WATCH from IS_AVAILABLE_ON, and date-blind on temporal questions.
        # `superseded` is no longer emitted (retirement is conveyed by `invalid_at`/"until").
        row: dict[str, Any] = {
            "kind": "edge",
            "id": item.uuid,
            "fact": (payload.get("fact") or payload.get("memory") or "").strip(),
            "score": score_out,
        }
        relation = str(payload.get("name") or "").strip()
        if relation:
            row["relation"] = relation
        chunk_id = str(payload.get("chunk_id") or "").strip()
        if chunk_id:
            row["source_episode"] = chunk_id
        stated = str(payload.get("stated") or "").strip()
        if stated:
            row["stated"] = stated
        # Eval vocabulary (item 6): surface dates under the SAME names the answerer prompt uses —
        # `as_of` = valid_at (became true, always present now), `until` = invalid_at (stopped being
        # true, only when the model asked for show_expiry). Emit each only when it has a value.
        if payload.get("valid_at"):
            row["as_of"] = payload.get("valid_at")
        if payload.get("invalid_at"):
            row["until"] = payload.get("invalid_at")
        return row

    if item.kind == "entity":
        name = str(payload.get("name") or "").strip()
        summary = str(payload.get("summary") or payload.get("memory") or "").strip()
        if summary.startswith(f"About {name}:"):
            summary = summary[len(f"About {name}:") :].strip()
        # Fidelity fix (item 2): surface the entity TYPE — present in the row but dropped here, so
        # the agent couldn't distinguish a catalog/list entity from a subject profile.
        row = {
            "kind": "entity",
            "id": item.uuid,
            "name": name,
            "summary": summary,
            "score": score_out,
        }
        entity_type = str(payload.get("entity_type") or "").strip()
        # Drop the base "Entity" label — it means "no specific ontology type", so surfacing it is
        # noise that doesn't help the agent distinguish a typed subject from an untyped one.
        if entity_type and entity_type != "Entity":
            row["entity_type"] = entity_type
        return row

    text = str(payload.get("memory") or payload.get("content") or "").strip()
    row = {
        "kind": "episode",
        "id": item.uuid,
        "text": text,
        "score": score_out,
    }
    # Eval vocabulary (item 6): an episode's single timestamp IS its `stated` (said) date.
    stated = payload.get("valid_at")
    if stated:
        row["stated"] = stated
    return row


# --- Text rendering of a tool result (replaces the JSON dump fed back to the model) ----------
# Switched 2026-06: the agent saw each search result as `json.dumps(payload)`. The JSON braces /
# quotes / repeated key names are ~30% pure token overhead at equal fidelity, and that result is
# re-sent on every later agent turn — so we render plain `#facts/#entities/#episodes` lines instead,
# mirroring the eval answerer's layout. The dict still flows to the trace (unchanged); only the
# model-facing text changes.
_NEWLINE_RUN = re.compile(r"\s*\n+\s*")


def _collapse(text: str, sep: str = " ") -> str:
    """Flatten internal newlines to ONE line (option A): entity summaries stack several distinct
    facts on separate lines and episodes carry markdown line breaks — both must render as a single
    bullet so the per-kind layout stays one-item-per-line for the agent."""
    return _NEWLINE_RUN.sub(sep, (text or "").strip())


def _score_key(item: dict[str, Any]) -> float:
    """Sort key: items are emitted score-descending within each section (None/absent score last)."""
    score = item.get("score")
    return float(score) if isinstance(score, (int, float)) else -1.0


def _fact_text_line(item: dict[str, Any]) -> str:
    """`- [stated] <fact> [<relation> / as of <date> / until <date> / score]` — `until` only when the
    edge carried it (show_expiry). Mirrors the metadata the answerer's fact line surfaces."""
    bits: list[str] = []
    relation = str(item.get("relation") or "").strip()
    if relation:
        bits.append(relation)
    if item.get("as_of"):
        bits.append(f"as of {item['as_of']}")
    if item.get("until"):
        bits.append(f"until {item['until']}")
    score = item.get("score")
    if isinstance(score, (int, float)):
        bits.append(f"score {score:.2f}")
    body = _collapse(str(item.get("fact") or ""))
    meta = f" [{' / '.join(bits)}]" if bits else ""
    stated = str(item.get("stated") or "").strip()
    return f"- [{stated}] {body}{meta}" if stated else f"- {body}{meta}"


def _entity_text_line(item: dict[str, Any]) -> str:
    """`- <name> (<entity_type>): <summary> [score]` — type only when present; summary collapsed."""
    name = str(item.get("name") or "").strip()
    etype = str(item.get("entity_type") or "").strip()
    head = f"{name} ({etype})" if name and etype else (name or "entity")
    summary = _collapse(str(item.get("summary") or ""), sep="; ")
    line = f"- {head}: {summary}" if summary else f"- {head}"
    score = item.get("score")
    return f"{line} [score {score:.2f}]" if isinstance(score, (int, float)) else line


def _episode_text_line(item: dict[str, Any]) -> str:
    """`- [stated] <text> [score]` — the verbatim turn, collapsed to one line."""
    when = str(item.get("stated") or "").strip()
    body = _collapse(str(item.get("text") or ""))
    line = f"- [{when}] {body}" if when else f"- {body}"
    score = item.get("score")
    return f"{line} [score {score:.2f}]" if isinstance(score, (int, float)) else line


# (item kind, section heading, line formatter) — order is the answerer's: facts → entities → messages.
_TEXT_SECTIONS: tuple[tuple[str, str, Any], ...] = (
    ("edge", "#facts", _fact_text_line),
    ("entity", "#entities", _entity_text_line),
    ("episode", "#episodes", _episode_text_line),
)


def render_search_result_text(payload: dict[str, Any]) -> str:
    """Render a ``search_memory`` result (a ``SearchMemoryResult`` dump) as plain-text sections
    instead of JSON. One sub-result block per sub-query: a `## S{sid} - {goal} (returned N, new N)`
    header (with ` ERROR: …` appended on a failed sub-query), then `#facts`/`#entities`/`#episodes`
    sections (only the kinds present), one bullet per item, score-descending. Ends with a single
    `(accumulated_total N)` line. Keeps every metadata field the agent reasons over (relation, dates,
    score, name, type, summary) — drops only the JSON scaffolding and the unused `id`/`source_episode`."""
    lines: list[str] = []
    for sub in payload.get("sub_results") or []:
        goal = str(sub.get("goal") or "").strip()
        head = f"## S{sub.get('sid')} - {goal} (returned {sub.get('returned')}, new {sub.get('new')})"
        if sub.get("error"):
            head += f" ERROR: {sub['error']}"
        lines.append(head)
        items = list(sub.get("items") or [])
        for kind, heading, fmt in _TEXT_SECTIONS:
            rows = sorted(
                (it for it in items if it.get("kind") == kind), key=_score_key, reverse=True
            )
            if not rows:
                continue
            lines.append(heading)
            lines.extend(fmt(it) for it in rows)
        lines.append("")
    lines.append(f"(accumulated_total {payload.get('accumulated_total')})")
    return "\n".join(lines)


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
        # M1 fix: an omitted ``limit`` resolves to the admin-settable ``limit_default`` (was a
        # hardcoded 20), then the [min, max] clamp applies.
        requested_limit = q.limit if q.limit is not None else self._limits.limit_default
        clamped_limit = max(self._limits.limit_min, min(self._limits.limit_max, requested_limit))
        eff_hops = min(q.hops, self._limits.hops_max)
        if clamped_limit != requested_limit or eff_hops != q.hops:
            log.debug(
                "search_memory clamped · sid=%d · limit %d→%d · hops %d→%d",
                sid,
                requested_limit,
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
                # Tag this sub-query's pipeline trace with its sid so the trajectory UI can
                # open the exact retrieval trace for S{sid}.
                sid=sid,
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
    "render_search_result_text",
]
