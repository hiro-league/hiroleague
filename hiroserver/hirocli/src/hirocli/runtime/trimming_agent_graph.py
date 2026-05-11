"""LangGraph ReAct agent with fixed latest-message trimming.

The checkpointed ``messages`` state is pruned to the latest six messages before
model calls and after each turn finishes. No external memory model is used.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, RemoveMessage, SystemMessage
from langgraph.graph import END, MessagesState, START, StateGraph
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.prebuilt import ToolNode
from langgraph.types import Checkpointer

from hiro_commons.log import Logger

log = Logger.get("AGENT")
TRIMMED_MESSAGE_LIMIT = 6


class HiroAgentState(MessagesState):
    """Thread state trimmed to the latest messages only."""


def _token_counter():
    from langchain_core.messages.utils import count_tokens_approximately

    return count_tokens_approximately


def _model_input_summary_row(m: AnyMessage, *, preview_chars: int = 80) -> dict[str, Any]:
    """One compact row for model-input debug logs."""
    role = getattr(m, "type", "?")
    if isinstance(m, AIMessage) and m.tool_calls:
        return {
            "role": role,
            "len": "tool_calls",
            "preview": str(m.tool_calls)[:preview_chars],
        }
    content = m.content
    if isinstance(content, str):
        return {
            "role": role,
            "len": len(content),
            "preview": content[:preview_chars],
        }
    return {
        "role": role,
        "len": len(str(content)),
        "preview": str(content)[:preview_chars],
    }


def _trim_messages_to_latest(
    messages: list[AnyMessage],
    *,
    limit: int = TRIMMED_MESSAGE_LIMIT,
) -> list[AnyMessage | RemoveMessage]:
    """Return a LangGraph update that replaces state with the latest ``limit`` messages."""
    if len(messages) <= limit:
        return []
    return [RemoveMessage(id=REMOVE_ALL_MESSAGES), *messages[-limit:]]


def build_trimming_agent_graph(
    *,
    model: BaseChatModel,
    tools: list,
    system_prompt: str | None,
    checkpointer: Checkpointer | None,
):
    """Compile a checkpointer-backed ReAct graph with fixed latest-six message memory."""
    token_counter = _token_counter()
    model_with_tools = model.bind_tools(tools) if tools else model

    async def trim_messages(state: HiroAgentState) -> dict[str, Any]:
        messages = state["messages"]
        update = _trim_messages_to_latest(messages)
        if update:
            log.fineinfo(
                "Agent memory trimmed - HiroServer",
                before_count=len(messages),
                after_count=TRIMMED_MESSAGE_LIMIT,
            )
            return {"messages": update}
        return {}

    async def call_model(state: HiroAgentState) -> dict[str, Any]:
        msgs = state["messages"]
        msgs_for_model: list[AnyMessage] = (
            [SystemMessage(content=system_prompt), *msgs]
            if system_prompt
            else list(msgs)
        )
        log.fineinfo(
            "Chat model input - HiroServer",
            model_invoke_token_estimate=token_counter(msgs_for_model),
            model_invoke_message_count=len(msgs_for_model),
            retained_message_count=len(msgs),
            retained_message_limit=TRIMMED_MESSAGE_LIMIT,
            model_input_summary=[
                _model_input_summary_row(m) for m in msgs_for_model
            ],
        )

        response = await model_with_tools.ainvoke(msgs_for_model)
        return {"messages": [response]}

    def should_continue(state: HiroAgentState) -> str:
        last_message = state["messages"][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "tools"
        return "trim_after_turn"

    builder = StateGraph(HiroAgentState)
    builder.add_node("trim_before_model", trim_messages)
    builder.add_node("call_model", call_model)
    builder.add_node("trim_after_turn", trim_messages)
    builder.add_edge(START, "trim_before_model")
    builder.add_edge("trim_before_model", "call_model")
    builder.add_edge("trim_after_turn", END)

    if tools:
        builder.add_node("tools", ToolNode(tools))
        builder.add_conditional_edges(
            "call_model",
            should_continue,
            ["tools", "trim_after_turn"],
        )
        builder.add_edge("tools", "trim_before_model")
    else:
        builder.add_edge("call_model", "trim_after_turn")

    return builder.compile(checkpointer=checkpointer)
