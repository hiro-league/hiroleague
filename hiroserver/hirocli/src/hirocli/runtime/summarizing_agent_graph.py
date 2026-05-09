"""LangGraph ReAct agent with LangMem token-threshold summarization (Step 1 memory).

Summarization runs before each LLM call and again after tool execution so long
tool traces stay bounded. Full message history remains in checkpoint ``messages``;
the model receives ``summarized_messages`` from LangMem ``SummarizationNode``.
``fineinfo`` lines (logger ``AGENT``) record ``model_input_summary`` (same shape as
``history_summary`` in ``agent_manager``) for the exact list passed to the chat
model; ``summarizer_input_summary`` uses ``debug`` when a summary is triggered; and
``✂️ Summary executed`` at info level with token counts and the summary text.
"""

from __future__ import annotations

import ast
from typing import Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, SystemMessage
from langgraph.graph import END, MessagesState, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Checkpointer
from langmem.short_term import SummarizationNode

from hiro_commons.log import Logger

from ..domain.preferences import MemoryPreferences

log = Logger.get("AGENT")
_SUMMARY_PREFIX = "Summary of the conversation so far: "


class HiroAgentState(MessagesState):
    """Thread state: full ``messages`` history plus LangMem ``context`` (running summary)."""

    context: dict[str, Any]


class _LLMInputState(TypedDict):
    messages: list[AnyMessage]
    summarized_messages: list[AnyMessage]
    context: dict[str, Any]


def _token_counter_for(model: BaseChatModel):
    fn = getattr(model, "get_num_tokens_from_messages", None)
    if callable(fn):
        return fn
    from langchain_core.messages.utils import count_tokens_approximately

    return count_tokens_approximately


def _model_input_summary_row(m: AnyMessage, *, preview_chars: int = 80) -> dict[str, Any]:
    """One row for debug logs — same shape as agent_manager ``history_summary`` entries."""
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


def _text_from_content(content: Any) -> str:
    """Collapse provider-native content blocks to user-visible text."""
    if isinstance(content, str):
        return _strip_summary_block_repr(content)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
            elif isinstance(item, str) and item:
                parts.append(item)
        return "\n".join(parts)
    return str(content)


def _strip_summary_block_repr(text: str) -> str:
    if not text.startswith(_SUMMARY_PREFIX):
        return text
    raw = text[len(_SUMMARY_PREFIX):]
    if not raw.startswith("["):
        return text
    try:
        parsed = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return text
    clean = _text_from_content(parsed).strip()
    return f"{_SUMMARY_PREFIX}{clean}" if clean else text


def _sanitize_summary_result(result: dict[str, Any]) -> None:
    """Remove provider-only block metadata from LangMem summary state/messages."""
    ctx = result.get("context")
    if isinstance(ctx, dict):
        running_summary = ctx.get("running_summary")
        if running_summary is not None:
            summary = getattr(running_summary, "summary", None)
            clean_summary = _text_from_content(summary).strip()
            if clean_summary and clean_summary != summary:
                running_summary.summary = clean_summary

    for message in result.get("summarized_messages", []) or []:
        content = getattr(message, "content", None)
        clean_content = _text_from_content(content)
        if clean_content and clean_content != content:
            message.content = clean_content


def _clamp_summary_budget(mem: MemoryPreferences) -> tuple[int, int, int]:
    """Return (max_tokens, max_tokens_before_summary, max_summary_tokens) for LangMem.

    LangMem requires ``max_summary_tokens < max_tokens``.
    """
    max_ctx = max(512, int(mem.max_context_tokens))
    raw_before = mem.max_tokens_before_summary
    before = max_ctx if raw_before is None else int(raw_before)
    before = max(256, min(before, max_ctx))
    max_sum = int(mem.max_summary_tokens)
    max_sum = min(max_sum, max_ctx - 1)
    max_sum = max(64, max_sum)
    if max_sum >= max_ctx:
        max_sum = max(64, max_ctx // 4)
    return max_ctx, before, max_sum


def _bind_summary_token_limit(model: BaseChatModel, max_tokens: int):
    """Bind the provider-specific output token limit for the summarizer model."""
    if type(model).__module__.startswith("langchain_google_genai."):
        return model.bind(max_output_tokens=max_tokens)
    return model.bind(max_tokens=max_tokens)


def _has_non_system_content(messages: list[AnyMessage]) -> bool:
    """Return true when the provider request has at least one real chat turn."""
    for message in messages:
        if isinstance(message, SystemMessage):
            continue
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return True
        if content:
            return True
        if isinstance(message, AIMessage) and message.tool_calls:
            return True
    return False


def _latest_non_system_message(messages: list[AnyMessage]) -> AnyMessage | None:
    for message in reversed(messages):
        if not isinstance(message, SystemMessage):
            return message
    return None


def build_summarizing_agent_graph(
    *,
    model: BaseChatModel,
    summarization_model: BaseChatModel,
    tools: list,
    system_prompt: str | None,
    checkpointer: Checkpointer | None,
    memory: MemoryPreferences,
):
    """Compile a checkpointer-backed ReAct graph: summarize → model → [tools → summarize …]."""
    max_ctx, before_sum, max_sum = _clamp_summary_budget(memory)
    token_counter = _token_counter_for(model)

    summarization_node = SummarizationNode(
        model=_bind_summary_token_limit(summarization_model, max_sum),
        max_tokens=max_ctx,
        max_tokens_before_summary=before_sum,
        max_summary_tokens=max_sum,
        token_counter=token_counter,
    )

    async def summarize_with_logging(state: HiroAgentState) -> dict[str, Any]:
        """Wrap SummarizationNode so we can detect and log when a summary is actually produced."""
        prev_ctx = state.get("context") or {}
        prev_rs = prev_ctx.get("running_summary")
        prev_summary_text = prev_rs.summary if prev_rs else None

        pre_tokens = token_counter(state["messages"])

        result = await summarization_node.ainvoke(state)
        _sanitize_summary_result(result)

        new_ctx = result.get("context") or prev_ctx
        new_rs = new_ctx.get("running_summary")
        new_summary_text = new_rs.summary if new_rs else None

        if new_summary_text is not None and new_summary_text != prev_summary_text:
            post_tokens = token_counter(result.get("summarized_messages", []))
            thread_msgs = state["messages"]
            summarizer_input = [
                _model_input_summary_row(m) for m in thread_msgs[-30:]
            ]
            log.debug(
                f"⬇️ Summarizer input — HiroServer · short-term memory · {len(thread_msgs)} messages",
                summarizer_input_summary=summarizer_input,
                pre_summary_tokens=pre_tokens,
            )
            log.info(
                f"✂️ Summary executed — HiroServer · short-term memory · {pre_tokens}/{before_sum}",
                summary=new_summary_text,
                post_summary_tokens=post_tokens,
            )

        return result

    model_with_tools = model.bind_tools(tools) if tools else model

    async def call_model(state: _LLMInputState) -> dict[str, Any]:
        msgs = state["summarized_messages"]
        ctx = state.get("context") or {}
        rs = ctx.get("running_summary")
        msgs_for_model: list[AnyMessage] = (
            [SystemMessage(content=system_prompt), *msgs]
            if system_prompt
            else list(msgs)
        )
        if not _has_non_system_content(msgs_for_model):
            latest_message = _latest_non_system_message(state.get("messages", []))
            if latest_message is not None:
                msgs_for_model.append(latest_message)
                log.warning(
                    "⚠️ Summary left no model content — HiroServer · appended latest turn",
                    summarized_message_count=len(msgs),
                    fallback_role=getattr(latest_message, "type", "?"),
                )
        tok_invoke = token_counter(msgs_for_model)
        model_input_summary = [
            _model_input_summary_row(m) for m in msgs_for_model[-30:]
        ]
        if len(msgs_for_model) > 30:
            model_input_summary = [
                {"role": "…", "len": len(msgs_for_model) - 30, "preview": "(earlier messages omitted)"},
                *model_input_summary,
            ]

        label = (
            "⬇️ Chat model input (with summary) — HiroServer · short-term memory"
            if rs is not None
            else "⬇️ Chat model input — HiroServer"
        )
        log.fineinfo(
            label,
            model_invoke_token_estimate=tok_invoke,
            model_invoke_message_count=len(msgs_for_model),
            model_input_summary=model_input_summary,
        )

        response = await model_with_tools.ainvoke(msgs_for_model)
        return {"messages": [response]}

    def should_continue(state: HiroAgentState) -> str:
        last_message = state["messages"][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "tools"
        return END

    builder = StateGraph(HiroAgentState)
    builder.add_node("summarize", summarize_with_logging)
    builder.add_node("call_model", call_model, input_schema=_LLMInputState)
    builder.add_edge(START, "summarize")
    builder.add_edge("summarize", "call_model")

    if tools:
        builder.add_node("tools", ToolNode(tools))
        builder.add_conditional_edges(
            "call_model",
            should_continue,
            ["tools", END],
        )
        builder.add_edge("tools", "summarize")
    else:
        builder.add_edge("call_model", END)

    return builder.compile(checkpointer=checkpointer)
