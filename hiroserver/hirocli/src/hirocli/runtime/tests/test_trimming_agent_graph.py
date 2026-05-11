from __future__ import annotations

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage
from langgraph.graph.message import add_messages

from hirocli.runtime.trimming_agent_graph import (
    TRIMMED_MESSAGE_LIMIT,
    build_trimming_agent_graph,
    _trim_messages_to_latest,
)


def test_trim_messages_to_latest_keeps_latest_six() -> None:
    messages = [
        HumanMessage(content=f"message {i}", id=str(i))
        for i in range(TRIMMED_MESSAGE_LIMIT + 2)
    ]

    merged = add_messages(messages, _trim_messages_to_latest(messages))

    assert merged == messages[-TRIMMED_MESSAGE_LIMIT:]


def test_trim_messages_to_latest_noops_at_limit() -> None:
    messages = [
        HumanMessage(content=f"message {i}", id=str(i))
        for i in range(TRIMMED_MESSAGE_LIMIT)
    ]

    assert _trim_messages_to_latest(messages) == []


@pytest.mark.asyncio
async def test_graph_checkpoints_only_latest_six_messages() -> None:
    messages = [
        HumanMessage(content=f"message {i}", id=str(i))
        for i in range(TRIMMED_MESSAGE_LIMIT + 1)
    ]
    graph = build_trimming_agent_graph(
        model=FakeListChatModel(responses=["reply"]),
        tools=[],
        system_prompt=None,
        checkpointer=None,
    )

    result = await graph.ainvoke({"messages": messages})

    assert [message.content for message in result["messages"]] == [
        "message 2",
        "message 3",
        "message 4",
        "message 5",
        "message 6",
        "reply",
    ]
