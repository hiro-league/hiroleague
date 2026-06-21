"""Pure helpers for ``LLMNodes.call_model_node`` and the knowledge ``call_model``.

Split into two single-purpose functions (review §2.4) so the knowledge answer node can
reuse ``prepend_system`` without dragging in the chat-only turn-context injection.
"""

from __future__ import annotations

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage

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
