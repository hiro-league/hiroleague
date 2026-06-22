"""Bounded retrieval-agent loop for the memory-eval recall leg (P3, refactored P9, P10).

Two phases, deliberately split because only OpenAI exposes "tools + a fixed response schema in
one call" — Anthropic/Gemini/DeepSeek/Ollama do not (verified against the installed integrations):

1. **Search loop** — the model is bound with ``search_memory`` (``bind_tools``) and runs up to
   ``max_agent_turns - 1`` turns, emitting ONE ``search_memory`` call per turn (whose ``queries``
   list holds the decomposition; the tool runs the sub-queries concurrently). It stops early by
   emitting a turn with no tool call.
2. **Final structured turn** — ONE dedicated call with NO tools, via ``with_structured_output``,
   yields :class:`RetrievalFinal` = the declared ``reduce`` op + a free-text ``answer``. Because it
   binds no competing tool, structured output works on every provider (DeepSeek thinking mode falls
   back to ``json_mode`` inside ``with_structured_output_compat`` — hence the JSON shape is spelled
   out in ``_FINAL_TURN_INSTRUCTION``, since field descriptions never reach the model there).

The caller (``runner_memory``) runs the declared reduce over the accumulator and feeds the result
to the answerer; the loop's own ``answer_text`` is kept for the trace/parity but the eval re-answers
from the reduced context.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

from hiro_commons.log import Logger
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hirocli.domain.preferences import RetrievalAgentLimits
from hirocli.services.memory.agent.accumulator import Accumulator
from hirocli.services.memory.agent.reduce import ReduceOp
from hirocli.services.memory.agent.search_tool import SearchMemoryArgs, SearchMemoryTool
from hirocli.services.memory.graphiti_conversation import GraphitiConversationMemory

log = Logger.get("SVC.MEMORY.AGENT.RETRIEVAL")

_VALID_REDUCE_OPS = frozenset(get_args(ReduceOp))


class ReduceArgs(BaseModel):
    """Op-specific args for a declared reduce (typed, NOT a free-form dict — an open object breaks
    strict json-schema structured output on Gemini/OpenAI). Unused fields stay ``None`` and are
    dropped before reaching ``apply_reduce``."""

    kind: str | None = None  # distinct_count: which kind to count (edge | entity | episode)
    subject: str | None = None  # latest: subject filter
    attribute: str | None = None  # latest: attribute filter
    anchors: list[str] | None = None  # date_diff: the two anchor descriptions


class ReduceSpec(BaseModel):
    op: ReduceOp = "none"
    args: ReduceArgs = Field(default_factory=ReduceArgs)


class RetrievalFinal(BaseModel):
    """The dedicated final turn's structured output (design §5.4): the model's declared reduce op
    plus its free-text answer. Same shape across providers — read on every terminal turn."""

    reduce: ReduceSpec = Field(default_factory=ReduceSpec)
    answer: str = ""


# Appended as the last user turn before the structured call. Carries the AUTHORITATIVE JSON shape
# (json_mode/DeepSeek needs it spelled out — pydantic field descriptions don't reach the model) and
# flips the model from "search" to "finalize". Keep in sync with RetrievalFinal / reduce ops.
_FINAL_TURN_INSTRUCTION = (
    "You have finished searching. Using ONLY what the searches above returned, produce your final "
    "response as a single JSON object:\n"
    '{"reduce": {"op": "<none|distinct_count|order_by_time|latest|date_diff|keep_conflicting>", '
    '"args": {…}}, "answer": "<concise answer, or \'No information available.\' if unsupported>"}\n'
    "Pick the reduce op that matches the question's axis and let the system compute it — do NOT "
    "count, order, or do date math yourself:\n"
    "  count of distinct things → distinct_count, args {\"kind\": \"edge|entity|episode\"}\n"
    "  ordering / timeline       → order_by_time, args {}\n"
    "  current value of something that changed → latest, args {\"subject\": \"…\", \"attribute\": \"…\"}\n"
    "  duration between two events → date_diff, args {\"anchors\": [\"…\", \"…\"]}\n"
    "  both sides of an ever/never → keep_conflicting, args {}\n"
    "  anything else → none, args {}"
)


@dataclass
class RetrievalResult:
    accumulator: Accumulator
    reduce_op: str
    reduce_args: dict[str, Any]
    answer_text: str
    transcript: list[dict[str, Any]] = field(default_factory=list)
    # Set by the caller after it runs ``apply_reduce`` — the deterministic computed result
    # (count / days / conflict tallies) so the answerer can use it instead of recomputing.
    reduce_summary: dict[str, Any] = field(default_factory=dict)


def _tool_call_id(call: dict[str, Any]) -> str:
    return str(call.get("id") or call.get("name") or "unknown")


def _tool_call_name(call: dict[str, Any]) -> str:
    return str(call.get("name") or "")


def _tool_call_args(call: dict[str, Any]) -> dict[str, Any]:
    args = call.get("args")
    return dict(args) if isinstance(args, dict) else {}


def _normalize_reply_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content or "")


def _coerce_final(parsed: Any, raw: Any) -> tuple[str, dict[str, Any], str]:
    """Normalize the structured final turn into (op, args, answer), tolerating every provider shape.

    ``parsed`` is a :class:`RetrievalFinal` (json_schema/function_calling), a plain ``dict``
    (json_mode), or ``None`` (parse failed) — in which case we fall back to the raw message text.
    An unknown op degrades to ``none`` rather than letting ``apply_reduce`` raise downstream."""
    op = "none"
    args: dict[str, Any] = {}
    answer = ""

    if isinstance(parsed, RetrievalFinal):
        op = parsed.reduce.op
        args = parsed.reduce.args.model_dump(exclude_none=True)
        answer = parsed.answer
    else:
        data = parsed if isinstance(parsed, dict) else None
        if data is None and raw is not None:
            content = _normalize_reply_content(getattr(raw, "content", "")).strip()
            if content.startswith("{"):
                try:
                    data = json.loads(content)
                except json.JSONDecodeError:
                    data = None
            if data is None:
                # No JSON at all → treat the whole message as the answer, no reduce.
                return "none", {}, content
        if isinstance(data, dict):
            reduce = data.get("reduce")
            if isinstance(reduce, dict):
                op = str(reduce.get("op") or "none")
                args = {k: v for k, v in reduce.items() if k != "op" and v is not None}
            answer = str(data.get("answer") or "")

    if op not in _VALID_REDUCE_OPS:
        log.warning("⚠️ retrieval — unknown reduce op %r from model; using 'none'", op)
        op = "none"
    return op, args, str(answer or "")


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
            return payload, json.dumps(payload, ensure_ascii=False, default=str)
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


async def _final_structured_turn(
    *,
    model: BaseChatModel,
    messages: list[AnyMessage],
) -> tuple[str, dict[str, Any], str]:
    """One dedicated, tool-free call → declared reduce op + answer (design §5.4, P10).

    Routed through ``with_structured_output_compat`` so DeepSeek thinking mode (which 400s on the
    forced tool_choice) falls back to ``json_mode``; every other provider uses native json_schema.
    Never raises — a failed/empty structured turn degrades to ``none`` + empty answer."""
    from hirocli.domain.model_factory import with_structured_output_compat

    structured = with_structured_output_compat(model, RetrievalFinal, include_raw=True)
    final_messages = [*messages, HumanMessage(content=_FINAL_TURN_INSTRUCTION)]
    try:
        out = await structured.ainvoke(final_messages, config={"run_name": "retrieval_final"})
    except Exception:
        log.warning("⚠️ retrieval — final structured turn failed; reduce=none", exc_info=True)
        return "none", {}, ""

    if isinstance(out, dict):
        return _coerce_final(out.get("parsed"), out.get("raw"))
    return _coerce_final(out, None)


async def run_retrieval(
    *,
    question: str,
    memory: GraphitiConversationMemory,
    limits: RetrievalAgentLimits,
    prompt_text: str,
    model: BaseChatModel,
    user_id: int,
    character_id: str,
) -> RetrievalResult:
    """Drive the bounded retrieval loop; returns the populated accumulator + declared reduce/answer.

    The search loop gets ``max_agent_turns - 1`` tool-bound turns (the last turn is reserved for the
    dedicated structured final call, so total LLM invocations stay within ``max_agent_turns`` — the
    pref's documented meaning). The model stops searching early by emitting a turn with no tool call.
    """
    started_ms = int(time.perf_counter() * 1000)
    acc = Accumulator()
    search_tool = SearchMemoryTool(
        memory=memory,
        accumulator=acc,
        limits=limits,
        user_id=user_id,
        character_id=character_id,
    )
    lc_tool = build_search_memory_langchain_tool(search_tool)

    formatted_prompt = prompt_text.format(
        MAX_AGENT_TURNS=limits.max_agent_turns,
        MAX_PARALLEL_SEARCHES=limits.max_parallel_searches,
        MAX_LIMIT=limits.limit_max,
    )

    messages: list[AnyMessage] = [
        SystemMessage(content=formatted_prompt),
        HumanMessage(content=question),
    ]
    transcript: list[dict[str, Any]] = []
    cumulative_agent_turns = 0
    # One turn is reserved for the dedicated structured final call (see docstring).
    max_search_turns = max(0, limits.max_agent_turns - 1)
    search_model = model.bind_tools([lc_tool])

    for turn in range(1, max_search_turns + 1):
        cumulative_agent_turns += 1
        response = await search_model.ainvoke(messages)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=_normalize_reply_content(response))

        tool_calls = list(getattr(response, "tool_calls", None) or [])
        messages.append(response)
        if not tool_calls:
            # Model is done searching — break to the final structured turn.
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

    # Dedicated final structured turn (always runs; counts as one invocation).
    cumulative_agent_turns += 1
    reduce_op, reduce_args, answer_text = await _final_structured_turn(model=model, messages=messages)
    log.info(
        "✅ retrieval — agent · %d/%d turns · searches=%d · reduce=%s",
        cumulative_agent_turns,
        limits.max_agent_turns,
        acc.size(),
        reduce_op,
    )
    transcript.append(
        {
            "ts_ms": int(time.perf_counter() * 1000) - started_ms,
            "event": "final",
            "turn": cumulative_agent_turns,
            "cumulative_agent_turns": cumulative_agent_turns,
            "reduce_op": reduce_op,
            "answer_len_chars": len(answer_text),
        }
    )
    return RetrievalResult(
        accumulator=acc,
        reduce_op=reduce_op,
        reduce_args=reduce_args,
        answer_text=answer_text,
        transcript=transcript,
    )


__all__ = [
    "ReduceArgs",
    "ReduceSpec",
    "RetrievalFinal",
    "RetrievalResult",
    "build_search_memory_langchain_tool",
    "run_retrieval",
]
