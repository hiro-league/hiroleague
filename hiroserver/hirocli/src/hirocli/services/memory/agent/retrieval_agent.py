"""Bounded retrieval-agent loop for the memory-eval recall leg (P3, refactored P9, P10).

The model is bound with ``search_memory`` (``bind_tools``) and runs up to ``max_agent_turns``
turns, emitting ONE ``search_memory`` call per turn (whose ``queries`` list holds the
decomposition; the tool runs the sub-queries concurrently). The loop ends two ways:

- **Exit A (natural stop)** — the model emits a turn with NO tool call; that turn's content IS its
  final answer, so we reuse it (no extra call).
- **Exit B (budget exhausted)** — the loop hits the turn cap while still searching; there is no
  answer turn yet, so we run ONE tool-free ``_final_answer_turn`` to compose an answer over the
  full accumulator.

Reduce was removed (2026-06): the agent no longer declares a reduce op. The caller
(``runner_memory``) hands the accumulator (deduped/time-sorted) and this ``answer_text`` to the
answerer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from hiro_commons.log import Logger
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool

from hirocli.domain.preferences import RetrievalAgentLimits
from hirocli.runtime.agent_graph.graph_kit import normalize_reply_content
from hirocli.services.memory.agent.accumulator import Accumulator
from hirocli.services.memory.agent.agent_trace import compact_recall_item
from hirocli.services.memory.agent.search_tool import (
    SearchMemoryArgs,
    SearchMemoryQuery,
    SearchMemoryTool,
    render_search_result_text,
)
from hirocli.services.memory.graphiti_conversation import GraphitiConversationMemory

log = Logger.get("SVC.MEMORY.AGENT.RETRIEVAL")

# Appended as the last user turn for the exit-B answer call (tool-free) so the model composes a
# final answer over everything it found instead of searching again.
_FINAL_ANSWER_INSTRUCTION = (
    "You have finished searching. Using ONLY what the searches above returned, give your final "
    "answer — concise, or 'No information available.' if the searches don't support one."
)


@dataclass
class RetrievalResult:
    accumulator: Accumulator
    answer_text: str
    transcript: list[dict[str, Any]] = field(default_factory=list)
    # M2: count of failed sub-queries / tool errors across the loop, so the caller can mark the
    # memory_recall ledger node — otherwise a recall that returned nothing because every search
    # errored is indistinguishable from one that genuinely found nothing.
    error_count: int = 0


def _tool_call_id(call: dict[str, Any]) -> str:
    return str(call.get("id") or call.get("name") or "unknown")


def _tool_call_name(call: dict[str, Any]) -> str:
    return str(call.get("name") or "")


def _tool_call_args(call: dict[str, Any]) -> dict[str, Any]:
    args = call.get("args")
    return dict(args) if isinstance(args, dict) else {}


def _accumulate_message_usage(totals: dict[str, int], message: Any) -> None:
    """Sum one LLM reply's ``usage_metadata`` (input/output/cached/reasoning) into ``totals``.

    Fix: the agentic recall loop drives its own LLM calls, but their usage was never read into the
    ledger — so the ``memory_recall`` node stopped showing model/tokens/cost after the agentic
    refactor. We fold every turn's usage here and write the total once (see ``_write_recall_usage``).
    """
    meta = getattr(message, "usage_metadata", None)
    if not isinstance(meta, dict) or not meta:
        return
    from hirocli.runtime.agent_graph.graph_kit import usage_from_metadata

    usage = usage_from_metadata(meta)
    for key in ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens"):
        value = usage.get(key)
        if value is not None:
            totals[key] = totals.get(key, 0) + value


def _message_usage(message: Any) -> dict[str, int]:
    """One reply's usage as a standalone dict (per-turn, not accumulated).

    Used to stamp each transcript ``turn`` / ``answer`` event with its OWN token cost so the
    ``memory_recall`` node can flush a priced per-turn sub-row (Graph-Runs loop visibility) — the
    per-step counterpart to ``_accumulate_message_usage``'s running total."""
    totals: dict[str, int] = {}
    _accumulate_message_usage(totals, message)
    return totals


def _write_recall_usage(*, model_id: str, totals: dict[str, int]) -> None:
    """Attribute the loop's accumulated LLM token usage to the active ``memory_recall`` ledger entry.

    ``add_usage`` overwrites (not accumulates) and the rerank cost rides on separate child rows, so
    summing across all turns and writing once to the parent here is correct and conflict-free."""
    if not totals:
        return
    from hirocli.runtime.agent_graph.ledger.observe import observe

    # Pricing catalog is keyed by the prefixed ``provider:model`` id (mirrors judge's _ledger_llm_node);
    # a bare/blank model misses the catalog and prices as $0 while still showing the token counts.
    provider = model_id.partition(":")[0] if ":" in model_id else ""
    observe(usage={"provider": provider, "model": model_id, **totals})


def build_search_memory_langchain_tool(tool: SearchMemoryTool) -> StructuredTool:
    """Wrap :class:`SearchMemoryTool` for ``model.bind_tools``."""

    async def _search_memory(**kwargs: Any) -> dict[str, Any]:
        args = SearchMemoryArgs(**kwargs)
        result = await tool.call(args)
        return result.model_dump()

    return StructuredTool.from_function(
        coroutine=_search_memory,
        name=SearchMemoryTool.name,
        description=(
            "Search past conversation memory. Pass a `queries` list of 1..N sub-queries "
            "(decomposition runs them together). Returns one sub-result per sub-query with new "
            "deduped items plus counters (returned, new) and the running accumulated_total."
        ),
        args_schema=SearchMemoryArgs,
    )


async def _invoke_search_tool(
    lc_tool: StructuredTool,
    call: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    """Run the search_memory call; never raises — errors become tool-error content."""
    args = _tool_call_args(call)
    try:
        payload = await lc_tool.ainvoke(args)
        if isinstance(payload, dict):
            # Render the result as plain #facts/#entities/#episodes text, not JSON: ~30% fewer
            # context tokens at equal fidelity, and the result is re-sent every later turn. The dict
            # (`payload`) still flows to the trace below, so the trajectory UI/ledger are unchanged.
            return payload, render_search_result_text(payload)
        return None, str(payload)
    except Exception as exc:
        return None, f"Error: {exc}"


def _record_search_turn(
    *,
    transcript: list[dict[str, Any]],
    started_ms: int,
    turn: int,
    cumulative_agent_turns: int,
    call: dict[str, Any],
    payload: dict[str, Any] | None,
    content: str,
) -> None:
    """Append the ``tool_call`` + ``sub_result`` (or ``tool_error``) trace rows for one search call.

    Shapes match ``agent_trace.build_retrieval_loop_payload`` — keep them aligned."""
    call_id = _tool_call_id(call)
    sub_queries = _tool_call_args(call).get("queries")
    n_sub = len(sub_queries) if isinstance(sub_queries, list) else 0
    transcript.append(
        {
            "ts_ms": int(time.perf_counter() * 1000) - started_ms,
            "event": "tool_call",
            "turn": turn,
            "sub_queries": n_sub,
            "cumulative_agent_turns": cumulative_agent_turns,
        }
    )
    if payload is not None:
        accumulated_total = payload.get("accumulated_total")
        for sub in payload.get("sub_results") or []:
            # Compact preview of the NEW facts this sub-query added (top few, text+score) so the
            # ``memory_recall/search`` sub-row's output_preview shows the real recalled content, not
            # just counts. ``rerank`` (present only when the loop deferred it) rides along so the
            # ordered ``memory_recall/rerank`` sub-row can be built from the same transcript row.
            new_items = [
                compact_recall_item(item) for item in (sub.get("items") or [])[:3]
            ]
            transcript.append(
                {
                    "ts_ms": int(time.perf_counter() * 1000) - started_ms,
                    "event": "sub_result",
                    "turn": turn,
                    "sid": sub.get("sid"),
                    "goal": sub.get("goal") or "",
                    "query": sub.get("query") or "",
                    "temporal": sub.get("temporal") or "current",
                    "limit": sub.get("limit", 20),
                    "hops": sub.get("hops", 1),
                    "show_expiry": bool(sub.get("show_expiry")),
                    "returned": sub.get("returned"),
                    "new": sub.get("new"),
                    "accumulated_total": accumulated_total,
                    "error": sub.get("error"),
                    "new_items": new_items,
                    "rerank": sub.get("rerank"),
                    "dur_ms": sub.get("elapsed_ms"),
                }
            )
    elif content and content.startswith("Error:"):
        transcript.append(
            {
                "ts_ms": int(time.perf_counter() * 1000) - started_ms,
                "event": "tool_error",
                "turn": turn,
                "tool_call_id": call_id,
                "error": content,
            }
        )


async def _verbatim_fallback_search(
    *,
    question: str,
    search_tool: SearchMemoryTool,
    started_ms: int,
    turn: int,
    transcript: list[dict[str, Any]],
) -> int:
    """Degenerate-trajectory floor (design §10): when the loop accumulated NOTHING — the model never
    searched, every sub-query errored, or the turn budget left no search turn (e.g.
    ``max_agent_turns=1``) — run ONE verbatim search with the raw question so recall is never worse
    than the pre-agentic single-shot baseline. Never raises; returns the count of items added."""
    args = SearchMemoryArgs(queries=[SearchMemoryQuery(query=question, goal="verbatim fallback")])
    try:
        result = await search_tool.call(args)
    except Exception:
        log.warning("⚠️ retrieval — verbatim fallback search failed", exc_info=True)
        return 0
    payload = result.model_dump()
    # Record it like a normal search turn so the trajectory UI / trace shows the fallback ran.
    _record_search_turn(
        transcript=transcript,
        started_ms=started_ms,
        turn=turn,
        cumulative_agent_turns=turn,
        call={"name": SearchMemoryTool.name, "args": args.model_dump(), "id": "verbatim_fallback"},
        payload=payload,
        content="",
    )
    return sum(int(sub.get("new") or 0) for sub in payload.get("sub_results") or [])


async def _final_answer_turn(
    *,
    model: BaseChatModel,
    messages: list[AnyMessage],
) -> tuple[str, Any]:
    """Exit B only: ONE tool-free call → a plain final answer over the accumulator. We invoke the
    tools-UNBOUND model (not ``search_model``) so it cannot search again and is forced to answer —
    provider-uniform, no structured-output schema needed. Never raises (degrades to empty answer).

    Returns ``(answer_text, raw_reply)`` — the raw reply carries ``usage_metadata`` for the ledger."""
    final_messages = [*messages, HumanMessage(content=_FINAL_ANSWER_INSTRUCTION)]
    try:
        reply = await model.ainvoke(final_messages, config={"run_name": "retrieval_final"})
    except Exception:
        log.warning("⚠️ retrieval — final answer turn failed; empty answer", exc_info=True)
        return "", None
    return normalize_reply_content(getattr(reply, "content", "")).strip(), reply


async def run_retrieval(
    *,
    question: str,
    memory: GraphitiConversationMemory,
    limits: RetrievalAgentLimits,
    prompt_text: str,
    model: BaseChatModel,
    user_id: int,
    character_id: str,
    model_id: str = "",
    history: list[AnyMessage] | None = None,
    allow_abstain: bool = False,
    user_name: str = "",
    agent_name: str = "",
    per_step_usage: bool = False,
) -> RetrievalResult:
    """Drive the bounded retrieval loop; returns the populated accumulator + declared reduce/answer.

    ``model_id`` is the prefixed ``provider:model`` id of ``model`` — threaded through so the loop's
    own LLM token usage can be priced and attributed to the ``memory_recall`` ledger node.

    ``max_agent_turns`` is the SEARCH-turn budget: the model gets that many tool-bound turns. The
    optional exit-B compose turn (a tool-free final answer, run only when the loop never stops on its
    own) is NOT counted against it, so total LLM invocations are at most ``max_agent_turns + 1``. The
    model stops searching early by emitting a turn with no tool call.

    Surface flags (Phase 0 seam — both default to the eval behavior so the eval track stays
    byte-identical): ``history`` seeds recent conversation turns *before* the question so turn 1 can
    resolve anaphora + decompose against real context (chat); ``allow_abstain`` lets a loop that
    recalled NOTHING return an empty result instead of running eval's verbatim-fallback floor (chat
    may legitimately need no memory).

    ``per_step_usage`` (chat, under ``observability=trace``) signals that the caller will flush a
    per-step sub-row breakdown, so the loop **defers** each sub-query's rerank ledger row (captured
    into the transcript for ordered emission) instead of flushing it live. The parent still gets the
    aggregate LLM cost either way (the per-turn sub-rows are flushed ``no_fold`` so nothing is
    double-counted). Eval keeps the default (``False``) — live rerank flush, no per-turn sub-rows.
    """
    started_ms = int(time.perf_counter() * 1000)
    acc = Accumulator()
    search_tool = SearchMemoryTool(
        memory=memory,
        accumulator=acc,
        limits=limits,
        user_id=user_id,
        character_id=character_id,
        # Under per-step usage (chat/trace) each search defers its rerank ledger row so the loop can
        # emit it in order (search → its rerank) as a ``memory_recall/rerank`` sub-node.
        defer_rerank_ledger=per_step_usage,
    )
    lc_tool = build_search_memory_langchain_tool(search_tool)

    # USER_NAME / AGENT_NAME let the prompt phrase queries with the real names — memory anchors facts
    # to the speaker's real name, so "Misho's wife" hits the entity hub + BM25 far better than "the
    # user's wife". Blank falls back to generic wording (today's behavior). Prompts without these
    # placeholders (the eval prompt) simply ignore the extra kwargs.
    formatted_prompt = prompt_text.format(
        MAX_AGENT_TURNS=limits.max_agent_turns,
        MAX_PARALLEL_SEARCHES=limits.max_parallel_searches,
        MAX_LIMIT=limits.limit_max,
        USER_NAME=(user_name or "").strip() or "the user",
        AGENT_NAME=(agent_name or "").strip() or "the assistant",
    )

    # Phase 0: chat seeds recent turns between the system prompt and the question so the first turn
    # resolves anaphora + decomposes against real context; eval passes history=None → the plain
    # system+question pair is unchanged (byte-identical).
    messages: list[AnyMessage] = [SystemMessage(content=formatted_prompt)]
    if history:
        messages.extend(history)
    messages.append(HumanMessage(content=question))
    transcript: list[dict[str, Any]] = []
    # Accumulates the loop's own LLM token usage across every turn; written once to the
    # memory_recall ledger entry at the end (the refactor dropped this, so the node showed $0).
    usage_totals: dict[str, int] = {}
    cumulative_agent_turns = 0
    # ``max_agent_turns`` == the SEARCH-turn budget (changed 2026-07-03): the model gets this many
    # tool-bound turns. The optional exit-B compose turn below is NOT a search turn, so it's not
    # counted here (total LLM calls are at most max_agent_turns + 1). Previously this was
    # ``max_agent_turns - 1`` (one turn "reserved" for the answer), which starved max_agent_turns=1
    # of ALL search turns — so a turns=1 recall could never search and always read as an abstain.
    max_search_turns = limits.max_agent_turns
    search_model = model.bind_tools([lc_tool])
    last_stop: AIMessage | None = None  # exit A: the no-tool stop turn whose content is the answer

    for turn in range(1, max_search_turns + 1):
        cumulative_agent_turns += 1
        t_turn = time.perf_counter()
        response = await search_model.ainvoke(messages)
        turn_dur_ms = int((time.perf_counter() - t_turn) * 1000)
        # Fold this search turn's tokens in before any coercion (usage rides on the raw reply).
        _accumulate_message_usage(usage_totals, response)
        turn_usage = _message_usage(response)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=normalize_reply_content(response))

        tool_calls = list(getattr(response, "tool_calls", None) or [])
        messages.append(response)
        # Per-turn transcript row (feeds the Graph-Runs per-turn sub-node): how many sub-queries the
        # model emitted this turn (0 = it stopped, exit A) + this turn's own token usage. Placed
        # BEFORE the search rows so the transcript reads turn → its searches, in loop order.
        n_sub_this_turn = sum(
            len(_tool_call_args(c).get("queries") or [])
            for c in tool_calls
            if _tool_call_name(c) == SearchMemoryTool.name
        )
        transcript.append(
            {
                "ts_ms": int(time.perf_counter() * 1000) - started_ms,
                "event": "turn",
                "turn": turn,
                "cumulative_agent_turns": cumulative_agent_turns,
                "kind": "search" if tool_calls else "stop",
                "sub_queries": n_sub_this_turn,
                # Real wall-clock of THIS turn's own LLM decision call (the builder widens a search
                # turn's displayed elapsed to also cover the searches it launched — see the builder).
                "dur_ms": turn_dur_ms,
                # A stop turn's content IS the answer (exit A) — stamp a preview so the
                # ``memory_recall/turn`` sub-row shows the real answer, not just "stopped".
                "content_preview": normalize_reply_content(response.content)[:160]
                if not tool_calls
                else "",
                **turn_usage,
            }
        )
        if not tool_calls:
            # Exit A — model stopped searching; this turn's content is its final answer.
            last_stop = response
            break

        # Answer EVERY tool_call id with a ToolMessage (real APIs reject the next call otherwise).
        for call in tool_calls:
            name = _tool_call_name(call)
            call_id = _tool_call_id(call)
            if name != SearchMemoryTool.name:
                messages.append(
                    ToolMessage(
                        content=f"Error: unknown tool '{name}'", tool_call_id=call_id, name=name
                    )
                )
                continue
            payload, content = await _invoke_search_tool(lc_tool, call)
            messages.append(
                ToolMessage(content=content or "", tool_call_id=call_id, name=SearchMemoryTool.name)
            )
            _record_search_turn(
                transcript=transcript,
                started_ms=started_ms,
                turn=turn,
                cumulative_agent_turns=cumulative_agent_turns,
                call=call,
                payload=payload,
                content=content,
            )

    # Exit A: the model stopped on its own with a real answer AND it actually searched (acc
    # populated) → reuse that stop turn as the answer; no extra call, no fallback needed.
    # Flatten the stop turn via the SHARED normalizer, NOT isinstance(str): Gemini/Anthropic
    # return content as a LIST of blocks ([{"type":"text","text":...}]), so a str-only check left
    # stop_text empty and forced the exit-B answer turn on EVERY question (duplicate answer call).
    stop_text = normalize_reply_content(last_stop.content).strip() if last_stop is not None else ""
    if acc.size() == 0 and allow_abstain:
        # Phase 0 abstain: the loop recalled nothing and this surface (chat) permits skipping — do
        # NOT run eval's verbatim fallback or a forced answer turn; return an empty draft so the
        # persona answers without memory. Eval keeps allow_abstain=False, so its floor below is
        # untouched.
        answer_text = ""
    elif stop_text and acc.size() > 0:
        answer_text = stop_text
    else:
        # Exit B (budget exhausted) or an empty/groundless stop. Degenerate floor first (design §10):
        # if the loop found nothing, run one verbatim search so recall is never worse than the
        # pre-agentic single-shot baseline; then ONE tool-free answer turn over the accumulator.
        if acc.size() == 0:
            log.warning(
                "⚠️ retrieval — empty accumulator after loop; running verbatim fallback · q='%s'",
                question[:80],
            )
            await _verbatim_fallback_search(
                question=question,
                search_tool=search_tool,
                started_ms=started_ms,
                turn=cumulative_agent_turns + 1,
                transcript=transcript,
            )
        # The exit-B compose call is NOT a search turn, so it does NOT advance the turn counter
        # (changed 2026-07-03) — the loop's search budget stays == max_agent_turns and the trajectory
        # reads e.g. "4 / 4" instead of "5 / 4".
        t_ans = time.perf_counter()
        answer_text, final_raw = await _final_answer_turn(model=model, messages=messages)
        ans_dur_ms = int((time.perf_counter() - t_ans) * 1000)
        _accumulate_message_usage(usage_totals, final_raw)
        # Exit-B compose call = its own priced sub-node (memory/recall_answer) under per_step_usage.
        transcript.append(
            {
                "ts_ms": int(time.perf_counter() * 1000) - started_ms,
                "event": "answer",
                "turn": cumulative_agent_turns,
                "cumulative_agent_turns": cumulative_agent_turns,
                "answer_len_chars": len(answer_text),
                "answer_preview": answer_text[:160],
                "dur_ms": ans_dur_ms,
                **_message_usage(final_raw),
            }
        )
    # Attribute the loop's total LLM cost to the parent memory_recall ledger node (like eval), so the
    # top recall row always reflects the recall's LLM cost. Under per_step_usage the per-turn/answer
    # sub-rows ALSO show their slice, but they're flushed ``no_fold`` (display-only) so the same
    # tokens aren't double-counted into the run total.
    _write_recall_usage(model_id=model_id, totals=usage_totals)
    log.info(
        "✅ retrieval — agent · %d/%d turns · searches=%d · answer_chars=%d",
        cumulative_agent_turns,
        limits.max_agent_turns,
        acc.size(),
        len(answer_text),
    )
    transcript.append(
        {
            "ts_ms": int(time.perf_counter() * 1000) - started_ms,
            "event": "final",
            "turn": cumulative_agent_turns,
            "cumulative_agent_turns": cumulative_agent_turns,
            "answer_len_chars": len(answer_text),
        }
    )
    # M2: tally search failures (per-sub-query errors + whole-tool errors) from the transcript so
    # the caller can mark the memory_recall ledger node — a recall emptied by errors must not look
    # like a clean "found nothing".
    error_count = sum(
        1
        for row in transcript
        if row.get("event") == "tool_error"
        or (row.get("event") == "sub_result" and row.get("error"))
    )
    return RetrievalResult(
        accumulator=acc,
        answer_text=answer_text,
        transcript=transcript,
        error_count=error_count,
    )


__all__ = [
    "RetrievalResult",
    "build_search_memory_langchain_tool",
    "run_retrieval",
]
