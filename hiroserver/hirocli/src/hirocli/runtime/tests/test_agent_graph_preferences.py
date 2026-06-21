from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from hirocli.domain.data_store import ensure_data_db, get_default_user_id
from hirocli.runtime.agent_graph.nodes.context import ContextNodes
from hirocli.runtime.agent_graph.nodes.memory import MemoryNodes
from hirocli.runtime.tests.graph_fakes import RecordingLedgerSink, make_agent_services
from hirocli.runtime.agent_graph.events import GRAPH_MEMORY_RETRIEVED, GRAPH_MEMORY_STORED
from hirocli.runtime.agent_graph.ledger import LedgerEntry, LedgerSink, current_entry
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime
from hirocli.domain.memory import MemoryAddResult, MemoryUsage


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
        ledger_sink=None,
    ) -> MemoryAddResult:
        self.added.append(
            {
                "content": content,
                "user_id": user_id,
                "run_id": run_id,
                "character_id": character_id,
                "metadata": metadata or {},
                "ledger_sink": ledger_sink,
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

    async def search(
        self,
        query: str,
        *,
        user_id: int,
        character_id: str,
        limit: int | None = None,
        threshold: float | None = None,
        rerank: bool | None = None,
        metadata_filters: dict | None = None,
    ) -> list[dict]:
        return [{"memory": "User prefers concise replies"}]

    async def list_all(self, *, user_id: int, character_id: str | None = None) -> list[dict]:
        return []

    async def clear_all(self, *, user_id: int, character_id: str | None = None) -> int:
        return 0


def _enable_memory(runtime: WorkspacePreferencesRuntime) -> None:
    runtime.update_many({"memory.enabled": True})


@pytest.mark.asyncio
async def test_trim_history_uses_runtime_chat_max_messages(tmp_path) -> None:
    runtime = WorkspacePreferencesRuntime(tmp_path)
    runtime.update("chat.max_messages", 3)
    services = make_agent_services(tmp_path, preferences=runtime)
    graph = ContextNodes(services)

    messages = [HumanMessage(content=f"m{i}") for i in range(5)]
    result = await graph.trim_history_node({"messages": messages})

    kept = result["messages"][1:]
    assert [msg.content for msg in kept] == ["m2", "m3", "m4"]


def test_llm_usage_payload_uses_langchain_usage_metadata_only() -> None:
    from hirocli.runtime.agent_graph.graph_kit import llm_usage_payload

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

    payload = llm_usage_payload(
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
async def test_memory_search_and_compose_context_injects_memory(tmp_path) -> None:
    memory = _MemoryService()
    runtime = WorkspacePreferencesRuntime(tmp_path)
    _enable_memory(runtime)
    services = make_agent_services(tmp_path, memory=memory, preferences=runtime)
    memory_group = MemoryNodes(services)
    context_group = ContextNodes(services)
    events = []

    result = await memory_group.memory_search_node(
        {"user_text": "what should you remember?", "character_id": "hiro"},
        events.append,
    )
    # context_build now stores ONLY the clean user turn — context must not enter messages.
    message_result = await context_group.context_build_node(
        {"user_text": "what should you remember?", **result}
    )
    # Memory is assembled ephemerally into turn_context by compose_context (blocks only, no persona).
    ctx_result = await context_group.compose_context_node(
        {"user_text": "what should you remember?", **result}, lambda _event: None
    )

    assert events[0]["event"] == GRAPH_MEMORY_RETRIEVED
    assert result["retrieved_memories"] == [{"memory": "User prefers concise replies"}]
    assert message_result["messages"][0].content == "what should you remember?"
    turn_context = ctx_result["turn_context"]
    # Persona is NOT in the context block (it stays a stable system message). Instructions lead,
    # then the Memories section renders the hit as a bullet.
    assert turn_context.startswith("## Instructions")
    assert "## Memories retrieved\n- User prefers concise replies" in turn_context


@pytest.mark.asyncio
async def test_memory_search_records_search_and_result_previews(tmp_path) -> None:
    memory = _MemoryService()
    runtime = WorkspacePreferencesRuntime(tmp_path)
    _enable_memory(runtime)
    sink = RecordingLedgerSink(tmp_path)
    services = make_agent_services(tmp_path, memory=memory, preferences=runtime, ledger_sink=sink)
    graph = MemoryNodes(services)

    await graph.memory_search_node(
        {"user_text": "tea preference?", "character_id": "hiro"},
        lambda _event: None,
    )

    row = sink.row("memory_search") or {}
    # Input carries the query + top_k (the only knob Graphiti recall uses; F4 dropped
    # threshold/rerank from the preview); output uses the ` · ` separator.
    assert str(row.get("input_preview") or "").startswith("q: tea preference?")
    assert "top_k=" in str(row.get("input_preview") or "")
    assert row.get("output_preview") == "results: 1 · User prefers concise replies"


@pytest.mark.asyncio
async def test_memory_out_stores_turn_after_reply_event(tmp_path) -> None:
    memory = _MemoryService()
    runtime = WorkspacePreferencesRuntime(tmp_path)
    _enable_memory(runtime)
    services = make_agent_services(tmp_path, memory=memory, preferences=runtime)
    graph = MemoryNodes(services)
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
    # User turn ONLY — the assistant reply is intentionally not ingested (decision D2).
    assert memory.added[0]["content"] == "remember that I like tea"
    assert memory.added[0]["user_id"] == get_default_user_id(tmp_path)
    assert memory.added[0]["run_id"] == "12"
    assert memory.added[0]["character_id"] == "hiro"
    assert memory.added[0]["metadata"] == {
        "message_id": "in-1",  # episode uuid → provenance back to the turn (decision D5)
        "thread_id": "thread-1",
        "channel_id": 12,
        "source": "conversation",
        "speaker": "",  # no user_name configured → graphiti_conversation falls back to "User"
        "timestamp": None,  # no inbound_envelope here → ingest stamps 'now'
    }


@pytest.mark.asyncio
async def test_store_turn_memory_threads_ledger_sink_and_leaves_row_usage_blank(tmp_path) -> None:
    """``memory_out`` forwards the turn's ledger_sink to the memory write (so Graphiti's
    ingest steps nest under this node in Graph Runs) and records decision + preview — but
    NOT usage: the extraction cost is priced on those nested sub-rows, so folding it onto the
    parent row too would double-count it in the turn total."""
    memory = _MemoryService()
    runtime = WorkspacePreferencesRuntime(tmp_path)
    _enable_memory(runtime)
    services = make_agent_services(tmp_path, memory=memory, preferences=runtime)
    graph = MemoryNodes(services)

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

    # The write is ledgered through the chat turn's own sink.
    assert memory.added[0]["ledger_sink"] is graph._ledger_sink
    # Parent row: decision + preview, but no usage folded on (cost is on the nested sub-rows).
    assert entry.decision_kind == "stored"
    assert entry.decision_detail == "ok"
    assert entry.output_preview == "stored: 1 · stored memory 1"
    assert entry.provider == ""
    assert entry.model == ""
    assert entry.input_tokens == ""
    assert entry.output_tokens == ""


@pytest.mark.asyncio
async def test_store_turn_memory_no_new_facts_is_not_a_failure(tmp_path) -> None:
    """A turn whose extraction ran but yielded no facts (``stored_count == 0``) is a NORMAL
    ``no_new_facts`` store, not a failure — Graphiti has no mem0-style silent-drop failure
    mode."""
    memory = _MemoryService(stored_count=0)
    runtime = WorkspacePreferencesRuntime(tmp_path)
    _enable_memory(runtime)
    services = make_agent_services(tmp_path, memory=memory, preferences=runtime)
    graph = MemoryNodes(services)

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

    assert entry.decision_kind == "stored"
    assert entry.decision_detail == "no_new_facts"
    assert entry.error_code == ""  # not a failure
    assert events[-1]["event"] == GRAPH_MEMORY_STORED
    assert events[-1]["payload"]["count"] == 0


@pytest.mark.asyncio
async def test_store_turn_memory_threads_message_timestamp(tmp_path) -> None:
    """The episode is anchored to the REAL turn time: ``routing.timestamp`` from the inbound
    envelope is threaded into ``metadata['timestamp']`` (→ episode reference_time), so temporal
    ordering/supersession stays honest even if ingest is later detached from the turn (D4)."""
    memory = _MemoryService()
    runtime = WorkspacePreferencesRuntime(tmp_path)
    _enable_memory(runtime)
    services = make_agent_services(tmp_path, memory=memory, preferences=runtime)
    graph = MemoryNodes(services)

    await graph._store_turn_memory(
        {
            "user_text": "remember that I moved to Tokyo",
            "inbound_id": "in-1",
            "chat_channel_id": 12,
            "character_id": "hiro",
            "thread_id": "thread-1",
            # Serialized UnifiedMessage shape (model_dump(mode="json")) → ISO timestamp.
            "inbound_envelope": {"routing": {"timestamp": "2026-06-07T10:30:00+00:00"}},
        },
        lambda _event: None,
        "Noted.",
    )

    assert memory.added[0]["metadata"]["timestamp"] == "2026-06-07T10:30:00+00:00"


@pytest.mark.asyncio
async def test_store_turn_memory_missing_envelope_timestamp_is_none(tmp_path) -> None:
    """No envelope (or no routing timestamp) ⇒ ``metadata['timestamp']`` is None, so ingest
    falls back to stamping 'now' — never an error."""
    memory = _MemoryService()
    runtime = WorkspacePreferencesRuntime(tmp_path)
    _enable_memory(runtime)
    services = make_agent_services(tmp_path, memory=memory, preferences=runtime)
    graph = MemoryNodes(services)

    await graph._store_turn_memory(
        {
            "user_text": "remember my name",
            "inbound_id": "in-1",
            "chat_channel_id": 12,
            "character_id": "hiro",
            "thread_id": "thread-1",
        },
        lambda _event: None,
        "Noted.",
    )

    assert memory.added[0]["metadata"]["timestamp"] is None
