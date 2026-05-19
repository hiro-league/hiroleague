from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from hirocli.domain.data_store import ensure_data_db, get_default_user_id
from hirocli.runtime.agent_graph.base import BaseAgentGraph, _llm_usage_payload
from hirocli.runtime.agent_graph.events import GRAPH_MEMORY_RETRIEVED, GRAPH_MEMORY_STORED
from hirocli.runtime.agent_graph.ledger import LedgerEntry, LedgerSink, current_entry
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime
from hirocli.services.memory.usage_capture import MemoryAddResult, MemoryUsage


class _MemoryService:
    def __init__(
        self,
        usage: MemoryUsage | None = None,
        *,
        stored_count: int = 1,
    ) -> None:
        self.added: list[dict] = []
        self._usage = usage
        self._stored_count = stored_count

    async def add(
        self,
        content: str,
        *,
        user_id: int,
        run_id: str,
        character_id: str,
        metadata: dict | None = None,
    ) -> MemoryAddResult:
        self.added.append(
            {
                "content": content,
                "user_id": user_id,
                "run_id": run_id,
                "character_id": character_id,
                "metadata": metadata or {},
            }
        )
        stored_items = tuple(
            {"memory": f"stored memory {idx + 1}"}
            for idx in range(self._stored_count)
        )
        return MemoryAddResult(
            usage=self._usage,
            stored_count=self._stored_count,
            stored_items=stored_items,
        )

    async def search(self, query: str, *, user_id: int, character_id: str, limit: int = 8) -> list[dict]:
        return [{"memory": "User prefers concise replies"}]

    async def list_all(self, *, user_id: int, character_id: str | None = None) -> list[dict]:
        return []

    async def clear_all(self, *, user_id: int, character_id: str | None = None) -> int:
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
async def test_memory_in_records_search_and_result_previews(tmp_path) -> None:
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
    entry = LedgerEntry(
        sink=LedgerSink(tmp_path),
        node="memory_in",
        run_id="run-1",
        step_index=1,
        captures=frozenset({"decision"}),
    )
    token = current_entry.set(entry)
    try:
        await graph.memory_in_node(
            {"user_text": "tea preference?", "character_id": "hiro"},
            lambda _event: None,
        )
    finally:
        current_entry.reset(token)

    assert entry.input_preview == "search: tea preference?"
    assert entry.output_preview == "results: 1; User prefers concise replies"


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
    assert memory.added[0]["user_id"] == get_default_user_id(tmp_path)
    assert memory.added[0]["run_id"] == "12"
    assert memory.added[0]["character_id"] == "hiro"
    assert memory.added[0]["metadata"] == {
        "thread_id": "thread-1",
        "channel_id": 12,
        "source": "conversation",
    }


@pytest.mark.asyncio
async def test_store_turn_memory_records_returned_usage(tmp_path) -> None:
    """When the memory service returns usage, ``memory_out`` records it on the ledger entry."""
    usage = MemoryUsage(
        provider="openai",
        model="openai:gpt-4o-mini",
        input_tokens=120,
        output_tokens=40,
        cached_input_tokens=10,
        reasoning_tokens=0,
        call_count=2,
    )
    memory = _MemoryService(usage=usage)
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

    sink = LedgerSink(tmp_path)
    entry = LedgerEntry(
        sink=sink,
        node="memory_out",
        run_id="run-1",
        step_index=1,
        captures=frozenset({"usage", "decision"}),
    )
    token = current_entry.set(entry)
    try:
        await graph._store_turn_memory(
            {
                "user_text": "remember that I like tea",
                "inbound_id": "in-1",
                "chat_channel_id": 12,
                "character_id": "hiro",
                "thread_id": "thread-1",
            },
            lambda _event: None,
            "Noted.",
        )
    finally:
        current_entry.reset(token)

    assert entry.provider == "openai"
    assert entry.model == "openai:gpt-4o-mini"
    assert entry.input_tokens == 120
    assert entry.output_tokens == 40
    assert entry.cached_input_tokens == 10
    assert entry.decision_kind == "stored"
    assert entry.output_preview == "stored: 1; stored memory 1"


@pytest.mark.asyncio
async def test_store_turn_memory_flags_dropped_extraction(tmp_path) -> None:
    """Mem0 silently dropping the extraction (e.g. parser failure) must
    surface as a failure on the ledger row, not as a successful store.
    """
    usage = MemoryUsage(
        provider="google",
        model="google:gemini-3-flash-preview",
        input_tokens=200,
        output_tokens=80,
        cached_input_tokens=0,
        reasoning_tokens=0,
        call_count=1,
    )
    memory = _MemoryService(usage=usage, stored_count=0)
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

    sink = LedgerSink(tmp_path)
    entry = LedgerEntry(
        sink=sink,
        node="memory_out",
        run_id="run-1",
        step_index=1,
        captures=frozenset({"usage", "decision"}),
    )
    events: list[dict] = []
    token = current_entry.set(entry)
    try:
        await graph._store_turn_memory(
            {
                "user_text": "just remember my name haha",
                "inbound_id": "in-1",
                "chat_channel_id": 12,
                "character_id": "hiro",
                "thread_id": "thread-1",
            },
            events.append,
            "Got it.",
        )
    finally:
        current_entry.reset(token)

    assert entry.decision_kind == "failed"
    assert entry.decision_detail == "extraction_dropped"
    assert entry.error_code == "memory_extraction_dropped"
    assert events[-1]["event"] == GRAPH_MEMORY_STORED
    assert events[-1]["payload"]["count"] == 0
