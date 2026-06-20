"""Unit tests for ``call_model_support.inject_turn_context`` (P2c)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from hirocli.runtime.agent_graph.nodes.call_model_support import inject_turn_context


def test_inject_turn_context_no_op_without_context_or_system() -> None:
    messages = [HumanMessage(content="hello")]
    assert inject_turn_context(messages, "", None) == messages


def test_inject_turn_context_enriches_last_human_not_tool_tail() -> None:
    messages = [
        HumanMessage(content="first"),
        AIMessage(content="", tool_calls=[{"id": "1", "name": "echo", "args": {}}]),
        ToolMessage(content="pong", tool_call_id="1"),
        HumanMessage(content="follow up"),
    ]
    out = inject_turn_context(messages, "ctx block", None)
    assert out[0].content == "first"
    assert out[-1].content == "ctx block\n\n## Last User Message\nfollow up"
    assert isinstance(out[-2], ToolMessage)


def test_inject_turn_context_prepends_system_prompt() -> None:
    messages = [HumanMessage(content="hi")]
    out = inject_turn_context(messages, "", "You are Hiro.")
    assert len(out) == 2
    assert isinstance(out[0], SystemMessage)
    assert out[0].content == "You are Hiro."
    assert out[1].content == "hi"


def test_inject_turn_context_system_and_enriched_human() -> None:
    messages = [HumanMessage(content="question?")]
    out = inject_turn_context(messages, "memory hits", "Persona")
    assert isinstance(out[0], SystemMessage)
    assert out[1].content == "memory hits\n\n## Last User Message\nquestion?"
