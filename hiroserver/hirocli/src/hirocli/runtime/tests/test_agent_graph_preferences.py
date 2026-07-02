from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from hirocli.domain.data_store import get_default_user_id
from hirocli.runtime.agent_graph.nodes.context import ContextNodes
from hirocli.runtime.agent_graph.nodes.memory import MemoryNodes
from hirocli.runtime.tests.graph_fakes import RecordingLedgerSink, make_agent_services
from hirocli.runtime.agent_graph.events import GRAPH_MEMORY_RETRIEVED, GRAPH_MEMORY_STORED
from hirocli.runtime.agent_graph.ledger import LedgerEntry, LedgerSink, current_entry
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime
from hirocli.domain.memory import MemoryAddResult, MemoryUsage
from hirocli.services.memory.agent import MemoryRetriever
from hirocli.services.memory.agent.accumulator import Accumulator
from hirocli.services.memory.agent.retrieval_agent import RetrievalResult


def _canned_recall(
    monkeypatch,
    *,
    text: str = "User prefers concise replies",
    draft: str = "They prefer concise replies.",
) -> None:
    """Phase 2: stub the retrieval model builder + the loop so a NODE test exercises the node's own
    behavior (rows / draft / decision / preview), not the loop internals (see test_retrieval_agent)."""
    acc = Accumulator()
    acc.merge([{"kind": "fact", "uuid": "e1", "memory": text, "fact": text}], search_id=1, goal="")
    transcript = [
        {"event": "tool_call", "turn": 1, "sub_queries": 1, "cumulative_agent_turns": 1},
        {"event": "sub_result", "turn": 1, "sid": 1, "returned": 1, "new": 1, "accumulated_total": 1},
        {"event": "final", "turn": 2, "cumulative_agent_turns": 2, "answer_len_chars": len(draft)},
    ]
    result = RetrievalResult(accumulator=acc, answer_text=draft, transcript=transcript)

    async def _fake_retrieve(query, **_kw):
        return result

    monkeypatch.setattr(
        "hirocli.services.memory.models.build_memory_retrieval_model",
        lambda *a, **k: (object(), "fake:model"),
    )
    monkeypatch.setattr(MemoryRetriever, "retrieve", staticmethod(_fake_retrieve))


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
async def test_memory_recall_and_compose_context_injects_memory(tmp_path, monkeypatch) -> None:
    memory = _MemoryService()
    runtime = WorkspacePreferencesRuntime(tmp_path)
    _enable_memory(runtime)
    _canned_recall(monkeypatch)
    services = make_agent_services(tmp_path, memory=memory, preferences=runtime)
    memory_group = MemoryNodes(services)
    context_group = ContextNodes(services)
    events = []

    result = await memory_group.memory_recall_node(
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
    # P2: the loop yields rich recall rows (kind/search_id/goal) + a draft grounding note.
    assert result["retrieved_memories"][0]["memory"] == "User prefers concise replies"
    assert result["memory_draft"] == "They prefer concise replies."
    assert message_result["messages"][0].content == "what should you remember?"
    turn_context = ctx_result["turn_context"]
    # Persona is NOT in the context block (it stays a stable system message). Instructions lead, then
    # the Memories section renders richly (P3): kind-grouped "### Relevant Facts" with the fact line.
    assert turn_context.startswith("## Instructions")
    assert "## Memories retrieved\n### Relevant Facts\n- User prefers concise replies" in turn_context
    # P4: the loop's draft rides as a "search conclusion" block + a light grounding nudge, both in
    # turn_context (not the persona system prompt).
    assert "## Memory search conclusion\nThey prefer concise replies." in turn_context
    assert "Use the recalled memory" in turn_context


@pytest.mark.asyncio
async def test_memory_recall_records_search_and_result_previews(tmp_path, monkeypatch) -> None:
    memory = _MemoryService()
    runtime = WorkspacePreferencesRuntime(tmp_path)
    _enable_memory(runtime)
    _canned_recall(monkeypatch)
    sink = RecordingLedgerSink(tmp_path)
    services = make_agent_services(tmp_path, memory=memory, preferences=runtime, ledger_sink=sink)
    graph = MemoryNodes(services)

    await graph.memory_recall_node(
        {"user_text": "tea preference?", "character_id": "hiro"},
        lambda _event: None,
    )

    row = sink.row("memory_recall") or {}
    # Input carries the query; output is the loop summary (searches/turns) + a facts preview.
    assert str(row.get("input_preview") or "").startswith("q: tea preference?")
    assert row.get("output_preview") == "searches=1 · turns=2 · User prefers concise replies"
    assert row.get("decision_kind") == "retrieved"
    assert str(row.get("decision_detail")) == "1"


def _patch_ingest(monkeypatch, *, returns: int, sink: list[dict]):
    """Replace the windowed-ingest controller with an async recorder — the node's job is to gather
    state/prefs and delegate; the controller's data.db/windowing behavior is covered by
    ``services/memory/test_windowed_ingest.py`` + ``test_windowing.py``."""
    import hirocli.services.memory.windowed_ingest as wi
    from hirocli.services.memory.windowed_ingest import WindowIngestResult

    async def _fake(_memory, **kwargs):
        sink.append(kwargs)
        return WindowIngestResult(facts=returns, triggers=("count",) if returns else ())

    monkeypatch.setattr(wi, "ingest_pending_windows", _fake)


@pytest.mark.asyncio
async def test_memory_out_delegates_to_windowed_ingest(tmp_path, monkeypatch) -> None:
    """memory_out gathers the turn + windowing prefs and delegates to the windowed controller,
    splicing the CURRENT reply so its exchange can complete with no lag."""
    memory = _MemoryService()
    runtime = WorkspacePreferencesRuntime(tmp_path)
    _enable_memory(runtime)
    services = make_agent_services(tmp_path, memory=memory, preferences=runtime)
    graph = MemoryNodes(services)

    calls: list[dict] = []
    _patch_ingest(monkeypatch, returns=1, sink=calls)
    events: list[dict] = []

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
    assert len(calls) == 1
    kw = calls[0]
    assert kw["channel_id"] == 12
    assert kw["character_id"] == "hiro"
    assert kw["run_id"] == "12"
    assert kw["user_id"] == get_default_user_id(tmp_path)
    # The current reply is spliced (external_id == the turn's reply_id) so no lag.
    assert kw["current_reply_text"] == "Noted."
    assert kw["current_reply_id"] == result["reply_id"]
    # Windowing knobs threaded from memory.extraction.* (defaults).
    assert kw["window_turns"] == 4
    assert kw["session_gap_minutes"] == 120
    assert kw["chunk_min_tokens"] == 1000


@pytest.mark.asyncio
async def test_store_turn_memory_threads_ledger_sink_and_leaves_row_usage_blank(
    tmp_path, monkeypatch
) -> None:
    """``memory_out`` forwards the turn's ledger_sink to the windowed write (so Graphiti's ingest
    steps nest under this node in Graph Runs) and records decision + preview — but NOT usage: the
    extraction cost is priced on the nested sub-rows, so folding it here too would double-count."""
    memory = _MemoryService()
    runtime = WorkspacePreferencesRuntime(tmp_path)
    _enable_memory(runtime)
    services = make_agent_services(tmp_path, memory=memory, preferences=runtime)
    graph = MemoryNodes(services)

    calls: list[dict] = []
    _patch_ingest(monkeypatch, returns=1, sink=calls)

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
            "reply-xyz",
        )
    finally:
        current_entry.reset(token)

    # The write is ledgered through the chat turn's own sink.
    assert calls[0]["ledger_sink"] is graph._ledger_sink
    # Parent row: decision + preview, but no usage folded on (cost is on the nested sub-rows).
    assert entry.decision_kind == "stored"
    assert entry.decision_detail == "ok"
    # Preview now carries the flush-trigger note for tuning.
    assert entry.output_preview == "stored: 1 · 1 window(s): count"
    assert entry.provider == ""
    assert entry.model == ""
    assert entry.input_tokens == ""
    assert entry.output_tokens == ""


@pytest.mark.asyncio
async def test_store_turn_memory_no_new_facts_is_not_a_failure(tmp_path, monkeypatch) -> None:
    """A turn that flushed no window / no facts (controller returns 0) is a NORMAL
    ``no_new_facts`` store, not a failure — the window may just still be accumulating."""
    memory = _MemoryService()
    runtime = WorkspacePreferencesRuntime(tmp_path)
    _enable_memory(runtime)
    services = make_agent_services(tmp_path, memory=memory, preferences=runtime)
    graph = MemoryNodes(services)

    calls: list[dict] = []
    _patch_ingest(monkeypatch, returns=0, sink=calls)

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
            "reply-abc",
        )
    finally:
        current_entry.reset(token)

    assert entry.decision_kind == "stored"
    assert entry.decision_detail == "no_new_facts"
    assert entry.error_code == ""  # not a failure
    assert events[-1]["event"] == GRAPH_MEMORY_STORED
    assert events[-1]["payload"]["count"] == 0


@pytest.mark.asyncio
async def test_store_turn_memory_skipped_without_channel(tmp_path, monkeypatch) -> None:
    """Windowing needs a durable channel to read pending turns from — a turn with no
    ``chat_channel_id`` skips ingestion cleanly (never calls the controller)."""
    memory = _MemoryService()
    runtime = WorkspacePreferencesRuntime(tmp_path)
    _enable_memory(runtime)
    services = make_agent_services(tmp_path, memory=memory, preferences=runtime)
    graph = MemoryNodes(services)

    calls: list[dict] = []
    _patch_ingest(monkeypatch, returns=1, sink=calls)

    await graph._store_turn_memory(
        {"user_text": "hi", "inbound_id": "in-1", "character_id": "hiro", "thread_id": "thread-1"},
        lambda _event: None,
        "Noted.",
        "reply-1",
    )

    assert calls == []  # no channel → no windowed ingest


def test_chat_graph_exposes_ledger_sink_for_run_accumulator(tmp_path) -> None:
    """Regression: agent_manager opens the per-turn RunAccumulator (which writes the chat ``@run``
    aggregate row + sets ``current_run``) from ``graph.services.ledger_sink``. ``ChatAgentGraph``
    exposes no ``_ledger_sink`` attribute, so if this path breaks, chat turns write NO ``@run`` row
    and vanish from the Graph Runs list (and memory ingests can't nest under the turn)."""
    from hirocli.runtime.agent_graph.chat import ChatAgentGraph

    services = make_agent_services(tmp_path)
    graph = ChatAgentGraph(services)
    # The EXACT resolution agent_manager.handle uses — must yield the same sink the nodes write to.
    sink = getattr(getattr(graph, "services", None), "ledger_sink", None)
    assert sink is not None
    assert sink is services.ledger_sink
