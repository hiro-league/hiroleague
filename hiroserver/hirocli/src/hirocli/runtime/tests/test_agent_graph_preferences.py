from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from hirocli.runtime.agent_graph.base import BaseAgentGraph, _llm_usage_payload
from hirocli.runtime.agent_graph.events import GRAPH_MEMORY_RETRIEVED, GRAPH_MEMORY_STORED
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime


class _MemoryService:
    def __init__(self) -> None:
        self.added: list[dict] = []

    async def add(self, content: str, *, user_id: str, agent_id: str, metadata: dict | None = None) -> None:
        self.added.append(
            {
                "content": content,
                "user_id": user_id,
                "agent_id": agent_id,
                "metadata": metadata or {},
            }
        )

    async def search(self, query: str, *, user_id: str, agent_id: str, limit: int = 8) -> list[dict]:
        return [{"memory": "User prefers concise replies"}]

    async def list_all(self, *, user_id: str, agent_id: str | None = None) -> list[dict]:
        return []

    async def clear_all(self, *, user_id: str, agent_id: str | None = None) -> int:
        return 0


def _enable_memory(runtime: WorkspacePreferencesRuntime) -> None:
    runtime.update_many(
        {
            "memory.default_llm": "openai:gpt-test",
            "memory.default_embedding_model": "openai:text-embedding-3-small",
            "memory.enabled": True,
        }
    )


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
    result = await graph.memory_in_node({"messages": messages}, lambda _event: None)

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


@pytest.mark.asyncio
async def test_memory_in_retrieves_and_context_build_prepends_memory(tmp_path) -> None:
    memory = _MemoryService()
    runtime = WorkspacePreferencesRuntime(tmp_path)
    _enable_memory(runtime)
    graph = BaseAgentGraph(
        workspace_path=tmp_path,
        stt_service=None,
        vision_service=None,
        tts_service=None,
        credential_store=None,
        checkpointer=None,
        memory_service=memory,
        preferences=runtime,
    )
    events = []

    result = await graph.memory_in_node(
        {"user_text": "what should you remember?", "character_id": "hiro"},
        events.append,
    )
    message_result = await graph.context_build_node(
        {"user_text": "what should you remember?", **result}
    )

    assert events[0]["event"] == GRAPH_MEMORY_RETRIEVED
    assert result["retrieved_memories"] == [{"memory": "User prefers concise replies"}]
    assert message_result["messages"][0].content.startswith(
        "Memory context:\n- User prefers concise replies\n\n"
    )


@pytest.mark.asyncio
async def test_memory_out_stores_turn_after_reply_event(tmp_path) -> None:
    memory = _MemoryService()
    runtime = WorkspacePreferencesRuntime(tmp_path)
    _enable_memory(runtime)
    graph = BaseAgentGraph(
        workspace_path=tmp_path,
        stt_service=None,
        vision_service=None,
        tts_service=None,
        credential_store=None,
        checkpointer=None,
        memory_service=memory,
        preferences=runtime,
    )
    events = []

    result = await graph.memory_out_node(
        {
            "messages": [AIMessage(content="Noted.")],
            "user_text": "remember that I like tea",
            "thread_id": "thread-1",
            "chat_channel_id": 12,
            "character_id": "hiro",
            "inbound_id": "in-1",
        },
        events.append,
    )

    assert result["reply_text"] == "Noted."
    assert events[-1]["event"] == GRAPH_MEMORY_STORED
    assert memory.added[0]["content"] == "User: remember that I like tea\nAssistant: Noted."
    assert memory.added[0]["metadata"] == {
        "thread_id": "thread-1",
        "channel_id": 12,
        "source": "conversation",
    }
