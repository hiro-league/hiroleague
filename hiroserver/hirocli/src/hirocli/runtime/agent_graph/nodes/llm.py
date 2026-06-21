"""LLM node group — bound chat model invocation + tool dispatch loop.

Split out of the old monolithic ``ConversationNodes`` (review §1.5).

- ``call_model`` — invoke the bound chat model with persona + turn context
- ``tools`` — dispatch any tool calls the model emitted
- ``should_continue`` (router) — loop back to ``call_model`` while the model keeps calling tools

Holds the model + tool wiring from ``ChatGraphConfig``: ``_model``, ``_bound`` (model with
tools attached), ``_tools_by_name`` (dispatch table). No retry policy at the graph layer —
the chat model client owns its own back-off, and a graph-level retry would double-charge
tokens.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from hiro_commons.log import Logger
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.types import StreamWriter

from ..config import ChatGraphConfig
from ..events import GRAPH_LLM_USAGE, GRAPH_TOOL_COMPLETED
from ..graph_kit import (
    IDENTITY_PEER_KEYS,
    emit,
    emit_for,
    llm_usage_payload,
    normalize_reply_content,
    tool_args_one_line,
    tool_call_args,
    tool_call_id,
    tool_call_name,
    tool_result_bounded,
)
from ..ledger import graph_logged, observe, record_child
from ..node_group import NodeGroup
from ..state import GraphState
from ._helpers import _error_slug
from .call_model_support import inject_turn_context

if TYPE_CHECKING:
    from ..services import AgentServices

log = Logger.get("AGENT.GRAPH")


def _llm_decision(message: AIMessage) -> tuple[str, str]:
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        return "tool_call", tool_call_name(tool_calls[0])
    content = normalize_reply_content(message.content)
    if content.strip():
        return "text_reply", "ok"
    return "empty", "no_content"


def _last_human_message_preview(messages: list[AnyMessage]) -> str:
    from langchain_core.messages import HumanMessage

    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return normalize_reply_content(message.content)
    return normalize_reply_content(messages[-1].content) if messages else ""


def _tool_calls_preview(tool_calls: list[dict[str, Any]]) -> str:
    if not tool_calls:
        return "reply: <empty>"
    names = [tool_call_name(call) or "unknown" for call in tool_calls[:4]]
    return f"tool_calls: {len(tool_calls)}; " + ", ".join(names)


def _tool_input_preview(tool_name: str, args: dict[str, Any]) -> str:
    try:
        arg_text = json.dumps(args, ensure_ascii=False, default=str)
    except TypeError:
        arg_text = str(args)
    return f"{tool_name or 'unknown'} args: {arg_text}"


def _tool_result_content(result: Any) -> str:
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except TypeError:
        return str(result)


class LLMNodes(NodeGroup):
    """Model-bound LLM and tool nodes — constructed per ``build(config)``."""

    def __init__(self, services: "AgentServices", config: ChatGraphConfig) -> None:
        super().__init__(services)
        self._model_id = config.model_id
        self._system_prompt = config.system_prompt
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens
        self._thinking = config.thinking
        self._tools = config.tools
        self._model = config.model
        self._bound = config.model.bind_tools(config.tools) if config.tools else config.model
        self._tools_by_name = {getattr(t, "name", ""): t for t in config.tools}

    def is_active(self, label: str) -> bool:
        """``tools`` is registered only when the build config supplied a non-empty tool list."""
        if label == "tools":
            return bool(self._tools)
        return True

    @staticmethod
    def should_continue(state: GraphState) -> str:
        """Tools-loop conditional edge: route to ``tools`` when the LLM asked for one."""
        msgs = state.get("messages", []) or []
        if not msgs:
            return "memory_out"
        last = msgs[-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return "memory_out"

    @graph_logged(captures={"usage", "decision"}, on_error="raise")
    async def call_model_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        messages: list[AnyMessage] = list(state.get("messages", []) or [])
        if not messages:
            observe(
                decision=("empty", "no_messages"),
                input="messages: 0",
                output="reply: <empty>",
            )
            return {}
        # Persona stays a stable system message (cache-friendly). The per-turn context block
        # (memory + knowledge + citation), assembled once by compose_context into
        # ``turn_context``, is injected ephemerally into the current user turn — context first,
        # question last — so it sits next to the query and never persists in ``messages``.
        # ``turn_context`` is absent for non-chat variants that skip compose_context.
        turn_context = (state.get("turn_context") or "").strip()
        inputs = inject_turn_context(messages, turn_context, self._system_prompt)
        # Preview the clean stored turn (not the enriched copy) + the tuning that ran. Model
        # is in the model column, so it's not repeated here.
        tuning = (
            f" · temp={self._temperature} max_tokens={self._max_tokens} thinking={self._thinking or 'off'}"
            if self._temperature is not None
            else ""
        )
        observe(input=f"text: {_last_human_message_preview(messages)}{tuning}")
        input_estimate = count_tokens_approximately(inputs)
        log.fineinfo(
            "call_model — input · count=%d tokens≈%d",
            len(inputs), input_estimate,
        )
        # Resolve identity up-front so a failed call still records WHICH model broke (the ledger
        # wrapper otherwise stamps only the exception class name, e.g. "googlegenerativeai").
        effective_model = self._model_id or str(state.get("model_id") or "")
        provider = effective_model.split(":", 1)[0] if ":" in effective_model else ""
        # Per-turn tools kill-switch: invoke the un-bound model when tools are disabled for this
        # turn (preference or per-chat opt-out) so no tool calls are emitted; should_continue then
        # routes to memory_out. ``bound`` already == model when no tools were compiled in.
        active = self._bound if state.get("tools_enabled", True) else self._model
        try:
            response = await active.ainvoke(inputs)
        except Exception as exc:
            # Record which model failed (the wrapper can't), then fail() adds decision + message;
            # re-raise so failure semantics are unchanged.
            observe(
                usage={"provider": provider, "model": effective_model},
                fail={"code": _error_slug(exc), "message": str(exc)},
            )
            raise
        usage_payload = llm_usage_payload(
            response,
            inbound_id=state.get("inbound_id", ""),
            chat_channel_id=int(state.get("chat_channel_id") or 0),
            model_id=self._model_id or str(state.get("model_id") or ""),
            estimated_input_tokens=input_estimate,
        )
        decision_kind, decision_detail = _llm_decision(response)
        reply_preview = normalize_reply_content(response.content)
        observe(
            usage={
                "provider": provider,
                "model": effective_model,
                "input_tokens": int(usage_payload.get("input_tokens") or input_estimate or 0),
                "output_tokens": int(usage_payload.get("output_tokens") or 0),
                "cached_input_tokens": int(usage_payload.get("cached_input_tokens") or 0),
                "reasoning_tokens": int(usage_payload.get("reasoning_tokens") or 0),
            },
            decision=(decision_kind, decision_detail),
            output=(
                f"reply: {reply_preview}"
                if reply_preview.strip()
                else _tool_calls_preview(getattr(response, "tool_calls", None) or [])
            ),
        )
        emit(writer, GRAPH_LLM_USAGE, usage_payload)
        return {"messages": [response]}

    @graph_logged(captures={"decision"}, flush=False, on_error="degrade")
    async def tools_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        messages: list[AnyMessage] = list(state.get("messages", []) or [])
        if not messages:
            return {}
        last = messages[-1]
        if not isinstance(last, AIMessage) or not last.tool_calls:
            return {}

        out: list[ToolMessage] = []
        for idx, call in enumerate(last.tool_calls):
            call_id = tool_call_id(call)
            tool_name = tool_call_name(call)
            args = tool_call_args(call)
            tool = self._tools_by_name.get(tool_name)
            started = time.perf_counter()
            status = "completed"
            error: str | None = None
            try:
                if tool is None:
                    raise KeyError(f"unknown tool: {tool_name}")
                result = await tool.ainvoke(args)
                content = _tool_result_content(result)
            except Exception as exc:
                status = "failed"
                error = str(exc)
                content = f"Error: {error}"

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if status == "completed":
                record_child(
                    node=f"tools/{_error_slug(tool_name) or 'unknown'}",
                    status="ok",
                    elapsed_ms=elapsed_ms,
                    branch_index=idx,
                    input=_tool_input_preview(tool_name, args),
                    output=f"result: {content}",
                    decision=("ok", "ok"),
                )
            else:
                record_child(
                    node=f"tools/{_error_slug(tool_name) or 'unknown'}",
                    status="error",
                    elapsed_ms=elapsed_ms,
                    branch_index=idx,
                    input=_tool_input_preview(tool_name, args),
                    output=f"error: {error}",
                    fail={"code": _error_slug(error or "tool_error"), "decision": "client_error"},
                )
            emit_for(
                writer,
                state,
                GRAPH_TOOL_COMPLETED,
                {
                    "tool_call_id": call_id,
                    "tool_name": tool_name,
                    "status": status,
                    "elapsed_ms": elapsed_ms,
                    "error": error,
                    "args": tool_args_one_line(args),
                    "result": tool_result_bounded(content)
                    if status == "completed"
                    else None,
                },
                identity_keys=IDENTITY_PEER_KEYS,
            )
            out.append(
                ToolMessage(
                    content=content,
                    tool_call_id=call_id or tool_name,
                )
            )

        return {"messages": out}
