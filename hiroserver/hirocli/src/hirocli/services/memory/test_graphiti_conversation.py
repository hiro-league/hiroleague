"""Tests for GraphitiConversationMemory (conversation memory on the Graphiti brain).

Pure: a fake GraphitiMemoryService records calls and returns canned stats/expansions —
no Kuzu, no graphiti_core. Verifies group scoping (``mem_user_char``), user-turn ingest
mapping (message episode, speaker, ``conversation`` role), facts-as-memory recall shape,
cross-character enumeration, clear/delete delegation, and empty-input no-ops.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hirocli.services.memory.graphiti_conversation import (
    GraphitiConversationMemory,
    memory_group_id,
)


class _FakeGraph:
    """Stand-in for GraphitiMemoryService — records calls, returns canned results."""

    def __init__(self, *, edges_total=2, facts=(), facts_list=None, groups=None) -> None:
        self.ingest_calls: list[dict] = []
        self.search_calls: list[dict] = []
        self.list_facts_calls: list[dict] = []
        self.list_group_calls: list[str] = []
        self.clear_calls: list[str] = []
        self.delete_calls: list[list[str]] = []
        self.closed = False
        # Observability tier the recall path reads to gate the trace sidecar (default = ledger,
        # so no RetrievalCapture is engaged in these tests).
        self.observability = "ledger"
        self._edges_total = edges_total
        self._facts = tuple(facts)
        self._facts_list = list(facts_list or [])
        self._groups = list(groups or [])

    async def ingest_chunks(self, episodes, *, source_role, group_id, **kwargs):
        self.ingest_calls.append(
            {
                "episodes": list(episodes),
                "source_role": source_role,
                "group_id": group_id,
                "ledger_sink": kwargs.get("ledger_sink"),
                "extra_extraction_instructions": kwargs.get("extra_extraction_instructions"),
            }
        )
        return SimpleNamespace(
            edges_total=self._edges_total, entities_total=0, tokens_input=0, tokens_output=0
        )

    async def search_chunk_ids(
        self, query, *, group_id, num_results, temporal, k_hop=None, show_expiry=False
    ):
        self.search_calls.append(
            {
                "query": query,
                "group_id": group_id,
                "num_results": num_results,
                "temporal": temporal,
                "k_hop": k_hop,
                "show_expiry": show_expiry,
            }
        )
        return SimpleNamespace(
            facts=self._facts, chunk_ids=(), facts_total=len(self._facts), facts_used=len(self._facts)
        )

    async def list_facts(self, group_ids, *, limit=None):
        self.list_facts_calls.append({"group_ids": list(group_ids), "limit": limit})
        return list(self._facts_list)

    async def list_group_ids(self, prefix):
        self.list_group_calls.append(prefix)
        return list(self._groups)

    async def clear_group(self, group_id):
        self.clear_calls.append(group_id)
        return 1

    async def delete_facts(self, uuids):
        self.delete_calls.append(list(uuids))
        return len(uuids)

    async def close(self):
        self.closed = True


def test_group_id_format() -> None:
    assert memory_group_id(42, "aria") == "mem_42_aria"
    # The trailing separator makes the per-user prefix unambiguous: mem_42_ is NOT a prefix
    # of mem_420_x, so cross-character enumeration can't bleed between users.
    assert not memory_group_id(420, "x").startswith("mem_42_")
    # Graphiti only accepts [A-Za-z0-9_-] in a group_id, so a stray char is slugged.
    assert memory_group_id(1, "hiro:bot") == "mem_1_hiro-bot"


@pytest.mark.asyncio
async def test_group_override_targets_eval_drawer() -> None:
    """An eval-scoped instance (group_override) routes EVERY add/search/clear to its own
    drawer instead of deriving mem_{user}_{character} — the §6 scoped-service-object that
    isolates the memory eval into eval_mem_{set} without touching the runtime memory path."""
    g = _FakeGraph(edges_total=1, groups=["eval_mem_adam"])
    mem = GraphitiConversationMemory(g, group_override="eval_mem_adam")

    # add → the override drawer, regardless of the (user, character) passed.
    await mem.add("I work at Brightloom", user_id=999, run_id="r", character_id="whatever")
    assert g.ingest_calls[0]["group_id"] == "eval_mem_adam"

    # search → the override drawer too.
    await mem.search("where do I work?", user_id=999, character_id="whatever")
    assert g.search_calls[0]["group_id"] == "eval_mem_adam"

    # clear_all → only the override drawer (no per-user enumeration).
    await mem.clear_all(user_id=999, character_id="whatever")
    assert g.clear_calls == ["eval_mem_adam"]
    assert g.list_group_calls == []  # never enumerated mem_{user}_ groups


@pytest.mark.asyncio
async def test_add_ingests_user_turn_as_message_episode() -> None:
    g = _FakeGraph(edges_total=3)
    mem = GraphitiConversationMemory(g)
    result = await mem.add(
        "I moved to Tokyo",
        user_id=42,
        run_id="chan-9",
        character_id="aria",
        metadata={"message_id": "msg-1", "speaker": "Adam"},
    )
    assert len(g.ingest_calls) == 1
    call = g.ingest_calls[0]
    assert call["source_role"] == "conversation"  # F7 gate role (user turn → memory)
    assert call["group_id"] == "mem_42_aria"
    ep = call["episodes"][0]
    assert ep.chunk_id == "msg-1"  # episode uuid == message id (provenance, D5)
    assert ep.document_id == "conv:chan-9"
    assert ep.text == "I moved to Tokyo"
    assert ep.source == "message"
    assert ep.speaker == "Adam"
    # facts learned == stored_count (facts-as-memory, D3)
    assert result.stored_count == 3
    assert result.usage is None  # fake graph fires no LLM calls → no usage captured


@pytest.mark.asyncio
async def test_windowed_add_binds_speaker_names_in_extraction_clause() -> None:
    # The {user}/{character} placeholders are filled with the metadata speaker names, so the
    # extractor knows which labelled speaker is the human vs the assistant (roles explicit).
    g = _FakeGraph()
    mem = GraphitiConversationMemory(
        g,
        extraction_instructions='"{user}" is the human; "{character}" is the AI. Extract {user} only.',
    )
    await mem.add(
        "[09:00] Misho: pizza\n[09:00] Aria: nice",
        user_id=1,
        run_id="c",
        character_id="aria",
        metadata={
            "message_id": "w1",
            "prerendered": True,
            "user_name": "Misho",
            "character_name": "Aria",
        },
    )
    instr = g.ingest_calls[0]["extra_extraction_instructions"]
    assert instr == '"Misho" is the human; "Aria" is the AI. Extract Misho only.'
    assert "{user}" not in instr and "{character}" not in instr
    assert g.ingest_calls[0]["episodes"][0].speaker == ""  # prerendered → not re-prefixed

    # Empty names fall back to the same labels the window body uses ("User" / "Assistant").
    await mem.add(
        "body", user_id=1, run_id="c", character_id="aria",
        metadata={"message_id": "w2", "prerendered": True},
    )
    instr2 = g.ingest_calls[1]["extra_extraction_instructions"]
    assert '"User" is the human; "Assistant" is the AI' in instr2


@pytest.mark.asyncio
async def test_add_empty_content_is_noop() -> None:
    g = _FakeGraph()
    mem = GraphitiConversationMemory(g)
    result = await mem.add("   ", user_id=1, run_id="c", character_id="a")
    assert g.ingest_calls == []
    assert result.stored_count == 0


@pytest.mark.asyncio
async def test_add_defaults_speaker_and_id() -> None:
    g = _FakeGraph()
    mem = GraphitiConversationMemory(g)
    await mem.add("hi", user_id=1, run_id="c", character_id="a")
    ep = g.ingest_calls[0]["episodes"][0]
    assert ep.speaker == "User"  # default speaker when none supplied
    assert ep.chunk_id == ""  # no message_id → empty (valid, just unciteable)


@pytest.mark.asyncio
async def test_add_falls_back_to_inbound_id() -> None:
    g = _FakeGraph()
    mem = GraphitiConversationMemory(g)
    await mem.add("hi", user_id=1, run_id="c", character_id="a", metadata={"inbound_id": "in-7"})
    assert g.ingest_calls[0]["episodes"][0].chunk_id == "in-7"


@pytest.mark.asyncio
async def test_add_threads_ledger_sink_and_returns_no_usage() -> None:
    """add() forwards the chat turn's ledger_sink to ingest_chunks (so Graphiti's write steps
    nest under memory_out in Graph Runs) and returns usage=None — extraction cost is priced on
    those nested sub-rows by graphiti's default usage sink, not lumped onto a MemoryUsage."""
    g = _FakeGraph(edges_total=2)
    mem = GraphitiConversationMemory(g)
    sentinel = object()  # stands in for the chat LedgerSink
    result = await mem.add("hi", user_id=1, run_id="c", character_id="a", ledger_sink=sentinel)

    assert result.usage is None
    assert result.stored_count == 2
    assert g.ingest_calls[0]["ledger_sink"] is sentinel


@pytest.mark.asyncio
async def test_add_ledger_sink_defaults_to_none() -> None:
    """No ledger_sink (CLI / tools / tests) → ingest runs unledgered, no error."""
    g = _FakeGraph(edges_total=0)
    mem = GraphitiConversationMemory(g)
    result = await mem.add("hi", user_id=1, run_id="c", character_id="a")
    assert result.usage is None
    assert g.ingest_calls[0]["ledger_sink"] is None


@pytest.mark.asyncio
async def test_search_returns_facts_as_memory() -> None:
    g = _FakeGraph(facts=("Adam lives in Tokyo (as of 2024-05-01)", "Adam works at Cedar"))
    mem = GraphitiConversationMemory(g)
    hits = await mem.search("where does adam live", user_id=42, character_id="aria")
    assert hits == [
        {"memory": "Adam lives in Tokyo (as of 2024-05-01)", "kind": "fact"},
        {"memory": "Adam works at Cedar", "kind": "fact"},
    ]
    call = g.search_calls[0]
    assert call["group_id"] == "mem_42_aria"
    # Default temporal lens follows the constructor's ``temporal_default`` (which the
    # factory snapshots from ``graph.temporal_default``); the constructor default is
    # ``"current"`` so an unscoped instance recalls only currently-valid facts.
    assert call["temporal"] == "current"
    # No explicit limit → the module fallback (_DEFAULT_RECALL_LIMIT); live recall passes an
    # explicit per-sub-query limit, so this fallback only covers limit-less callers.
    assert call["num_results"] == 8


@pytest.mark.asyncio
async def test_search_temporal_lens_follows_constructor_pref() -> None:
    """``temporal_default="all"`` propagates into the underlying graph search — proving the
    admin Settings → Graph → Temporal lens (default) actually drives memory recall (replaces
    the former D8 hardcode that pinned recall to ``current`` regardless of pref)."""
    g = _FakeGraph(facts=("Adam used to live in Berlin (as of 2018-01-01)",))
    mem = GraphitiConversationMemory(g, temporal_default="all")
    await mem.search("where did adam live before?", user_id=42, character_id="aria")
    assert g.search_calls[0]["temporal"] == "all"


@pytest.mark.asyncio
async def test_search_empty_query_is_noop() -> None:
    g = _FakeGraph(facts=("x",))
    mem = GraphitiConversationMemory(g)
    assert await mem.search("  ", user_id=1, character_id="a") == []
    assert g.search_calls == []


@pytest.mark.asyncio
async def test_search_limit_overrides_default() -> None:
    g = _FakeGraph()
    mem = GraphitiConversationMemory(g)
    await mem.search("q", user_id=1, character_id="a", limit=3)
    assert g.search_calls[0]["num_results"] == 3


@pytest.mark.asyncio
async def test_list_all_one_character_scopes_to_its_group() -> None:
    g = _FakeGraph(facts_list=[{"memory": "f1", "id": "e1", "group_id": "mem_42_aria"}])
    mem = GraphitiConversationMemory(g)
    out = await mem.list_all(user_id=42, character_id="aria")
    # Enriched with character (parsed from group_id) + source for the admin memory view.
    assert out == [
        {
            "memory": "f1",
            "id": "e1",
            "group_id": "mem_42_aria",
            "character_id": "aria",
            "source": "conversation",
        }
    ]
    assert g.list_facts_calls[0]["group_ids"] == ["mem_42_aria"]
    assert g.list_group_calls == []  # no enumeration when a character is given


@pytest.mark.asyncio
async def test_list_all_no_character_enumerates_user_groups() -> None:
    g = _FakeGraph(
        groups=["mem_42_aria", "mem_42_max"],
        facts_list=[{"memory": "f", "group_id": "mem_42_max"}],
    )
    mem = GraphitiConversationMemory(g)
    out = await mem.list_all(user_id=42)
    assert g.list_group_calls == ["mem_42_"]
    assert g.list_facts_calls[0]["group_ids"] == ["mem_42_aria", "mem_42_max"]
    assert out == [
        {"memory": "f", "group_id": "mem_42_max", "character_id": "max", "source": "conversation"}
    ]


@pytest.mark.asyncio
async def test_clear_all_counts_then_clears_each_group() -> None:
    g = _FakeGraph(
        groups=["mem_42_aria", "mem_42_max"], facts_list=[{"memory": "a"}, {"memory": "b"}]
    )
    mem = GraphitiConversationMemory(g)
    deleted = await mem.clear_all(user_id=42)
    assert deleted == 2  # facts that existed (mem0 parity: count before delete)
    assert set(g.clear_calls) == {"mem_42_aria", "mem_42_max"}


@pytest.mark.asyncio
async def test_clear_all_no_groups_returns_zero() -> None:
    g = _FakeGraph(groups=[])
    mem = GraphitiConversationMemory(g)
    assert await mem.clear_all(user_id=99) == 0
    assert g.clear_calls == []


@pytest.mark.asyncio
async def test_delete_forwards_edge_id() -> None:
    g = _FakeGraph()
    mem = GraphitiConversationMemory(g)
    await mem.delete("edge-7")
    assert g.delete_calls == [["edge-7"]]


@pytest.mark.asyncio
async def test_delete_many_forwards_trimmed_edge_ids() -> None:
    """delete_many (admin 'Clear shown') drops blanks, trims, and batches the edge ids to
    one graph delete; returns the count requested."""
    g = _FakeGraph()
    mem = GraphitiConversationMemory(g)
    n = await mem.delete_many(["e1", "  e2  ", "", "e3"])
    assert g.delete_calls == [["e1", "e2", "e3"]]
    assert n == 3


@pytest.mark.asyncio
async def test_delete_many_empty_is_noop() -> None:
    g = _FakeGraph()
    mem = GraphitiConversationMemory(g)
    assert await mem.delete_many([]) == 0
    assert g.delete_calls == []


@pytest.mark.asyncio
async def test_delete_blank_id_raises() -> None:
    g = _FakeGraph()
    mem = GraphitiConversationMemory(g)
    with pytest.raises(ValueError, match="Memory id is required"):
        await mem.delete("  ")


@pytest.mark.asyncio
async def test_close_delegates_to_graph_service() -> None:
    g = _FakeGraph()
    mem = GraphitiConversationMemory(g)
    await mem.close()
    assert g.closed is True


# --- create_memory_service factory (Phase 3: mem0 → Graphiti re-point) ---


def test_create_memory_service_none_when_memory_disabled(tmp_path) -> None:
    from hirocli.domain.preferences import MemoryPreferences, WorkspacePreferences
    from hirocli.services.memory import create_memory_service

    prefs = WorkspacePreferences(memory=MemoryPreferences(enabled=False))
    assert create_memory_service(tmp_path, prefs) is None


def test_create_memory_service_none_when_engine_unavailable(tmp_path) -> None:
    """Memory enabled but no graph engine configured (no extraction model / embedder) →
    None, gracefully (``from_preferences`` returns None, never raises)."""
    from hirocli.domain.preferences import MemoryPreferences, WorkspacePreferences
    from hirocli.services.memory import create_memory_service

    prefs = WorkspacePreferences(memory=MemoryPreferences(enabled=True))
    assert create_memory_service(tmp_path, prefs) is None


def test_create_memory_service_builds_graphiti_conversation(tmp_path, monkeypatch) -> None:
    """When enabled and the engine builds, the factory wraps the GraphitiMemoryService in a
    GraphitiConversationMemory, building even when graph RETRIEVAL is off
    (``require_backend=False``)."""
    from hirocli.domain.preferences import MemoryPreferences, WorkspacePreferences
    from hirocli.services.knowledge.graph import graphiti_service as gsvc_mod
    from hirocli.services.memory import create_memory_service

    captured: dict = {}

    def _fake_from_prefs(prefs, workspace_path, **kwargs):
        captured["require_backend"] = kwargs.get("require_backend")
        captured["on_usage"] = kwargs.get("on_usage", "unset")
        return _FakeGraph()

    monkeypatch.setattr(
        gsvc_mod.GraphitiMemoryService, "from_preferences", staticmethod(_fake_from_prefs)
    )

    prefs = WorkspacePreferences(memory=MemoryPreferences(enabled=True))
    service = create_memory_service(tmp_path, prefs)

    assert isinstance(service, GraphitiConversationMemory)
    assert captured["require_backend"] is False  # builds even when graph retrieval is off
    # No on_usage override passed: the client falls back to graphiti's default
    # ``record_episode_llm_usage`` sink, which prices the write on the nested Graph-Runs
    # sub-rows (not a separate MemoryUsage on the parent memory_out row).
    assert captured["on_usage"] == "unset"
