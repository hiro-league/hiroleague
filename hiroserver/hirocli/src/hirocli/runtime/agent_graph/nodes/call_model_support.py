"""Pure helpers for ``LLMNodes.call_model_node`` and the knowledge ``call_model``.

Split into two single-purpose functions (review §2.4) so the knowledge answer node can
reuse ``prepend_system`` without dragging in the chat-only turn-context injection.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage

from ..graph_kit import normalize_reply_content


def prepend_system(messages: list[AnyMessage], system_prompt: str | None) -> list[AnyMessage]:
    """Prepend a stable system message when ``system_prompt`` is non-empty.

    No-op when the prompt is empty/None — callers that need to enforce a non-empty
    persona should validate before calling.
    """
    if system_prompt:
        return [SystemMessage(content=system_prompt), *messages]
    return list(messages)


def enrich_last_human(messages: list[AnyMessage], turn_context: str) -> list[AnyMessage]:
    """Splice ephemeral turn context into the most recent human message in-place.

    The context block lives ABOVE the user text under a ``## Last User Message`` header so
    the model sees it as part of the current turn — never persisted into chat history.
    """
    context = turn_context.strip()
    if not context:
        return list(messages)
    out = list(messages)
    for index in range(len(out) - 1, -1, -1):
        if isinstance(out[index], HumanMessage):
            user_text = normalize_reply_content(out[index].content)
            out[index] = HumanMessage(
                content=f"{context}\n\n## Last User Message\n{user_text}"
            )
            break
    return out


def stale_note(tool_name: str) -> str:
    """What the model sees instead of a live tool's result from an earlier turn."""
    return (
        f"[Out of date: this {tool_name} result was read in an earlier turn and may no longer be true. "
        f"Call {tool_name} again for the current state.]"
    )


def retire_live_results(messages: list[AnyMessage], live_tool_names: frozenset[str]) -> list[AnyMessage]:
    """Show live tools' results from earlier turns as out of date (Tool.agent_live).

    Reason: the conversation keeps every tool result, so a live read (who is home) from an
    earlier turn sat in the history looking current, and Hiro answered from it instead of
    reading again ("Maro is away" an hour after Maro came home). Results in the current turn
    (after the last human message) stay as they are. The stored history is not changed: this
    copy is only what the model is sent.
    """
    if not live_tool_names:
        return list(messages)
    last_human = next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)), -1)
    # ToolMessages carry only the call id: map ids to tool names from the AI messages' calls.
    names_by_call: dict[str, str] = {}
    for message in messages[:last_human]:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                if call.get("id"):
                    names_by_call[str(call["id"])] = str(call.get("name") or "")
    out = list(messages)
    for index in range(max(last_human, 0)):
        message = out[index]
        if not isinstance(message, ToolMessage):
            continue
        name = message.name or names_by_call.get(message.tool_call_id, "")
        if name in live_tool_names:
            out[index] = ToolMessage(content=stale_note(name), tool_call_id=message.tool_call_id, name=name)
    return out


def inject_turn_context(
    messages: list[AnyMessage],
    turn_context: str,
    system_prompt: str | None,
) -> list[AnyMessage]:
    """Chat call_model's full input shape: enrich the last human turn + prepend persona.

    Composition over ``enrich_last_human`` + ``prepend_system`` so chat callers keep a
    single-line API; knowledge call_model uses ``prepend_system`` directly.
    """
    return prepend_system(enrich_last_human(messages, turn_context), system_prompt)
