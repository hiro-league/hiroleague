"""Bounded retrieval-agent loop for the memory-eval recall leg (P3, refactored in P9).

The model emits exactly ONE ``search_memory`` tool call per turn, whose ``queries`` list holds
the decomposition (the tool runs the sub-queries concurrently — see ``search_tool``). The loop's
only cap is ``max_agent_turns``: a counter advancing once per LLM invocation (we pay tokens for
every invocation, search or final). On the last allowed turn the model is invoked WITHOUT tools
so it can only produce a final answer (verbatim fallback against a runaway loop).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from hiro_commons.log import Logger
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool

from hirocli.domain.preferences import RetrievalAgentLimits
from hirocli.services.memory.agent.accumulator import Accumulator
from hirocli.services.memory.agent.search_tool import SearchMemoryArgs, SearchMemoryTool
from hirocli.services.memory.graphiti_conversation import GraphitiConversationMemory

log = Logger.get("SVC.MEMORY.AGENT.RETRIEVAL")


@dataclass
class RetrievalResult:
    accumulator: Accumulator
    reduce_op: str
    reduce_args: dict[str, Any]
    answer_text: str
    transcript: list[dict[str, Any]] = field(default_factory=list)


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


def parse_final_response(content: Any) -> tuple[str, dict[str, Any], str]:
    """Parse the model's terminal turn — optional JSON ``reduce`` + ``answer`` (design §5.4)."""
    text = _normalize_reply_content(content).strip()
    reduce_op = "none"
    reduce_args: dict[str, Any] = {}
    answer = text

    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return reduce_op, reduce_args, answer
        if isinstance(data, dict):
            reduce = data.get("reduce")
            if isinstance(reduce, dict):
                reduce_op = str(reduce.get("op") or "none")
                reduce_args = {k: v for k, v in reduce.items() if k != "op"}
            if "answer" in data:
                answer = str(data.get("answer") or "")
    return reduce_op, reduce_args, answer


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
    """Drive the bounded retrieval loop; returns the populated accumulator + final answer.

    Each ``while`` iteration is one LLM invocation = one agent turn. ``cumulative_agent_turns``
    advances per iteration; on the last allowed turn the model is invoked with NO tools so it
    must answer. Normally the model emits exactly one ``search_memory`` call per search turn; if
    it defensively emits several, each is dispatched and answered (still one agent turn).
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
    cumulative_agent_turns = 0
    transcript: list[dict[str, Any]] = []

    while True:
        cumulative_agent_turns += 1
        turn = cumulative_agent_turns
        # Last allowed invocation → strip tools so the model can ONLY answer (verbatim fallback).
        force_final = cumulative_agent_turns >= limits.max_agent_turns
        active = model if force_final else model.bind_tools([lc_tool])
        response = await active.ainvoke(messages)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=_normalize_reply_content(response))

        tool_calls = [] if force_final else list(getattr(response, "tool_calls", None) or [])

        if not tool_calls:
            reduce_op, reduce_args, answer_text = parse_final_response(response.content)
            log.info(
                "✅ retrieval — agent · %d/%d turns · reduce=%s",
                cumulative_agent_turns,
                limits.max_agent_turns,
                reduce_op,
            )
            transcript.append(
                {
                    "ts_ms": int(time.perf_counter() * 1000) - started_ms,
                    "event": "final",
                    "turn": turn,
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

        # Search turn: append the AIMessage, then answer EVERY tool_call id with a ToolMessage
        # (real LLM APIs reject the next invocation otherwise). Normally a single search_memory
        # call; a defensive multi-call burst is still one agent turn.
        messages.append(response)
        for call in tool_calls:
            call_id = _tool_call_id(call)
            name = _tool_call_name(call)
            if name != SearchMemoryTool.name:
                messages.append(
                    ToolMessage(
                        content=f"Error: unknown tool '{name}'", tool_call_id=call_id, name=name
                    )
                )
                transcript.append(
                    {
                        "ts_ms": int(time.perf_counter() * 1000) - started_ms,
                        "event": "tool_error",
                        "turn": turn,
                        "tool_call_id": call_id,
                        "error": f"unknown tool '{name}'",
                    }
                )
                continue

            payload, content = await _invoke_search_tool(lc_tool, call)
            messages.append(
                ToolMessage(content=content or "", tool_call_id=call_id, name=SearchMemoryTool.name)
            )
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


__all__ = [
    "RetrievalResult",
    "build_search_memory_langchain_tool",
    "parse_final_response",
    "run_retrieval",
]
