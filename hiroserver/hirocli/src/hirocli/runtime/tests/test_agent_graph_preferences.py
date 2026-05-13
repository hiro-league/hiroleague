from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from hirocli.runtime.agent_graph.base import BaseAgentGraph, _llm_usage_payload
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime


@pytest.mark.asyncio
async def test_memory_in_node_uses_runtime_memory_max_messages(tmp_path) -> None:
    runtime = WorkspacePreferencesRuntime(tmp_path)
    runtime.update("memory.max_messages", 3)
    graph = BaseAgentGraph(
        workspace_path=tmp_path,
        stt_service=None,
        vision_service=None,
        tts_service=None,
        credential_store=None,
        checkpointer=None,
        preferences=runtime,
    )

    messages = [HumanMessage(content=f"m{i}") for i in range(5)]
    result = await graph.memory_in_node({"messages": messages})

    kept = result["messages"][1:]
    assert [msg.content for msg in kept] == ["m2", "m3", "m4"]


def test_llm_usage_payload_uses_langchain_usage_metadata_only() -> None:
    msg = AIMessage(
        content="hi",
        usage_metadata={
            "input_tokens": 10,
            "output_tokens": 4,
            "total_tokens": 14,
            "input_token_details": {"cache_read": 3},
            "output_token_details": {"reasoning": 2},
        },
        response_metadata={
            "token_usage": {
                "prompt_tokens": 999,
                "completion_tokens": 999,
                "total_tokens": 1998,
            }
        },
    )

    payload = _llm_usage_payload(
        msg,
        inbound_id="in-1",
        chat_channel_id=1,
        model_id="openai:gpt-test",
        estimated_input_tokens=50,
    )

    assert payload == {
        "inbound_id": "in-1",
        "chat_channel_id": 1,
        "model_id": "openai:gpt-test",
        "usage_available": True,
        "input_tokens": 10,
        "output_tokens": 4,
        "total_tokens": 14,
        "cached_input_tokens": 3,
        "reasoning_tokens": 2,
    }
