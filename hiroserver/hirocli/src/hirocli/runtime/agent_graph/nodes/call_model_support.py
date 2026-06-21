"""Pure helpers for ``LLMNodes.call_model_node``."""

from __future__ import annotations

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage

from ..graph_kit import normalize_reply_content


def inject_turn_context(
    messages: list[AnyMessage],
    turn_context: str,
    system_prompt: str | None,
) -> list[AnyMessage]:
    """Enrich the last human turn with ephemeral context; prepend stable system prompt."""
    inputs: list[AnyMessage] = list(messages)
    context = turn_context.strip()
    if context:
        for index in range(len(inputs) - 1, -1, -1):
            if isinstance(inputs[index], HumanMessage):
                user_text = normalize_reply_content(inputs[index].content)
                inputs[index] = HumanMessage(
                    content=f"{context}\n\n## Last User Message\n{user_text}"
                )
                break
    if system_prompt:
        inputs = [SystemMessage(content=system_prompt), *inputs]
    return inputs
