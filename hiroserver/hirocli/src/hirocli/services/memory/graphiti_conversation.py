"""GraphitiConversationMemory — conversation long-term memory on the Graphiti brain.

Implements the :class:`~hirocli.domain.memory.MemoryService` Protocol (the
mem0 → Graphiti replacement, design docs/memory-graphiti-replacement-design.md §L2.1).
ONE temporal graph store serves both knowledge and conversation memory; conversation is
isolated per ``(user, character)`` via a ``mem_{user}_{character}`` group_id (decision
D1). Cross-character reads pass the union of a user's groups (``get_by_group_ids`` takes
a list), so per-character isolation and "all of a user's data" both work.

Facts-as-memory (decision D3): a remembered turn is ingested as a *message* episode,
Graphiti extracts dated facts (entities + relationships with ``valid_at``/``invalid_at``),
and recall returns those facts directly — there is no separate conversation passage
layer. Only the USER half of a turn is ever written (decision D2 / the F7 ``conversation``
gate), so the memory graph can't become a stale echo of its own output.

This facade owns conversation semantics only; all graph/Kuzu/graphiti_core access goes
through the injected :class:`GraphitiMemoryService`, keeping the brain rip-out-able.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from hiro_commons.log import Logger

from hirocli.domain.memory import MemoryAddResult

# Conversation-memory partition helpers live in the shared group-ID policy module so every
# vertical mints/validates group_ids through one closed grammar (docs/graph-group-policy-design.md).
# Re-exporting ``memory_group_id`` here keeps the existing import path for memory callers/tests.
from hirocli.services.knowledge.graph.group_scope import (
    character_from_group as _character_from_group,
    memory_group_id,
    memory_user_prefix as _user_groups_prefix,
)

if TYPE_CHECKING:
    from hirocli.runtime.agent_graph.ledger import LedgerSink
    from hirocli.services.knowledge.graph.graphiti_ingest import GraphEventSink
    from hirocli.services.knowledge.graph.graphiti_service import GraphitiMemoryService

log = Logger.get("SVC.MEMORY.GRAPHITI")


# Extraction-cost visibility (mem0 → Graphiti): the memory write now ledgers Graphiti's own
# per-episode / per-operation rows (extract / resolve_facts / persist …) NESTED under the
# ``memory_out`` node in Graph Runs — same machinery knowledge ingest uses. Those priced
# sub-rows are the single source of the write's token cost (they fold into the turn total),
# so the interim F1 "cost-on-the-memory_out-row" capture was retired to avoid double-counting
# (the memory LLM client now uses graphiti's default ``record_episode_llm_usage`` sink, which
# buckets tokens into the active episode ledger). See docs §L2.5 / §13b.


def _memory_row(fact: dict[str, Any]) -> dict[str, Any]:
    """Enrich a raw graph fact with the fields the admin memory view attributes on —
    ``character_id`` (parsed from the fact's ``group_id``) and ``source`` (always
    ``conversation`` for memory facts)."""
    group_id = str(fact.get("group_id", "") or "")
    return {
        **fact,
        "character_id": _character_from_group(group_id),
        "source": "conversation",
    }


def _parse_reference_time(value: Any) -> dt.datetime | None:
    """Best-effort parse of an episode reference time; ``None`` ⇒ ingest stamps 'now'."""
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


class GraphitiConversationMemory:
    """:class:`MemoryService` over :class:`GraphitiMemoryService`, scoped per (user, character)."""

    def __init__(
        self,
        graph_service: "GraphitiMemoryService",
        *,
        default_top_k: int = 8,
        event_sink: "GraphEventSink | None" = None,
    ) -> None:
        self._graph = graph_service
        self._default_top_k = int(default_top_k)
        # Optional live-viz sink: when set, each remembered turn streams its new nodes/edges
        # (tagged with the mem_ group) to the admin Graph tab via the DomainEventBus.
        self._event_sink = event_sink

    async def add(
        self,
        content: str,
        *,
        user_id: int,
        run_id: str,
        character_id: str,
        metadata: dict[str, Any] | None = None,
        ledger_sink: "LedgerSink | None" = None,
    ) -> MemoryAddResult:
        """Remember the USER half of a turn (decision D2). Returns the facts Graphiti
        learned this turn as ``stored_count`` (facts-as-memory).

        ``ledger_sink`` (the chat turn's sink) makes the write observable in Graph Runs:
        ``ingest_chunks`` records Graphiti's per-episode + per-operation rows, and since the
        chat turn already set ``current_run``, those rows NEST under the active ``memory_out``
        node (the caller sets ``current_substep``) and carry the priced extraction tokens.
        ``usage`` is therefore ``None`` here — token accounting lives on those sub-rows, not
        on a separate ``MemoryUsage`` (per the domain contract)."""
        text = str(content or "").strip()
        if not text:
            return MemoryAddResult(usage=None, stored_count=0)
        meta = dict(metadata or {})
        group = memory_group_id(user_id, character_id)
        # Episode uuid == message id ⇒ free provenance back to the stored turn (decision
        # D5). Fall back to inbound_id; empty ⇒ ingest mints no provenance link (still
        # works, just unciteable).
        message_id = str(meta.get("message_id") or meta.get("inbound_id") or "").strip()
        speaker = str(meta.get("speaker") or "User").strip() or "User"
        reference_time = _parse_reference_time(meta.get("timestamp"))
        # Lazy import keeps graphiti episode types off this module's import path until used.
        from hirocli.services.knowledge.graph.graphiti_ingest import GraphitiEpisodeInput

        episode = GraphitiEpisodeInput(
            chunk_id=message_id,
            document_id=f"conv:{run_id}",  # the conversation thread the turn came from
            text=text,
            reference_time=reference_time,
            source="message",  # speaker-aware episode (A3)
            speaker=speaker,
        )
        stats = await self._graph.ingest_chunks(
            [episode],
            source_role="conversation",
            group_id=group,
            ledger_sink=ledger_sink,
            event_sink=self._event_sink,  # live viz: stream new facts to the Graph tab
        )
        stored = int(getattr(stats, "edges_total", 0) or 0)
        log.info(
            "✅ memory — remembered turn · facts=%d · group=%s",
            stored,
            group,
        )
        return MemoryAddResult(usage=None, stored_count=stored)

    async def search(
        self,
        query: str,
        *,
        user_id: int,
        character_id: str,
        limit: int | None = None,
        threshold: float | None = None,
        rerank: bool | None = None,
        metadata_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Recall the current facts that bear on ``query`` (temporal lens ``current``,
        decision D8). Returns facts-as-memory dicts (``{"memory": dated_fact}``) in the
        shape ``context_assembly.memory_block`` renders.

        ``threshold`` / ``rerank`` are intentionally ignored: those gates are owned by the
        shared graph-engine knobs (``sim_min_score`` / reranker), not re-applied per call
        (decision L2.4). ``metadata_filters`` has no analog in the graph and is ignored."""
        q = str(query or "").strip()
        if not q:
            return []
        group = memory_group_id(user_id, character_id)
        top_k = self._default_top_k if limit is None else int(limit)
        # Ledger Graphiti's fact search as sub-steps of the active ``memory_search`` node
        # (embed_query / candidate_gen / bfs_expand / rrf_fuse / rerank + temporal_filter),
        # mirroring knowledge's ``graph_expand``. The tracer buffers graphiti's ``search.*``
        # spans; ``flush_graph_expand`` renders them onto the node's ledger entry. All of this
        # no-ops outside a ledgered chat turn (CLI / admin / tools / tests → no active entry).
        from hirocli.runtime.agent_graph.ledger import current_entry
        from hirocli.services.knowledge.graph.ledger_tracer import SpanRecord, current_spans

        spans: list[SpanRecord] = []
        spans_token = current_spans.set(spans)
        try:
            expansion = await self._graph.search_chunk_ids(
                q, group_id=group, num_results=top_k, temporal="current"
            )
        finally:
            current_spans.reset(spans_token)
        if (entry := current_entry.get()) is not None:
            from hirocli.services.knowledge.graph.retrieval_ledger import flush_graph_expand

            flush_graph_expand(
                entry,
                spans,
                expansion,
                temporal="current",  # memory recall is always the current lens (D8)
                ledger_detail=self._graph.ledger_detail,
            )
        # The kept, dated current facts ARE the recalled memories. Each fact text already
        # carries its validity date (e.g. "… (as of 2024-05-01)") from the search layer.
        # When ``graph.search_scope`` widens beyond ``edges``, the expansion also carries
        # entity summaries (attribute-style memories) and/or episode bodies (raw-turn BM25
        # recall). All three shapes blend into one memory list — the answer model decides
        # what's relevant (matches how the graph panel already mixes them).
        # ``GraphitiExpansion`` always carries these; the ``getattr`` defaults keep older
        # test fakes (SimpleNamespace with only ``facts``) working without per-test edits.
        node_memories = tuple(getattr(expansion, "node_memories", ()) or ())
        episode_memories = tuple(getattr(expansion, "episode_memories", ()) or ())
        hits: list[dict[str, Any]] = [{"memory": fact} for fact in expansion.facts]
        hits.extend({"memory": summary} for summary in node_memories)
        hits.extend({"memory": body} for body in episode_memories)
        log.info(
            "⬇️ memory — recalled · n=%d (facts=%d nodes=%d episodes=%d) · group=%s",
            len(hits),
            len(expansion.facts),
            len(node_memories),
            len(episode_memories),
            group,
        )
        return hits

    async def list_all(
        self,
        *,
        user_id: int,
        character_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """All remembered facts for a user — one character (``character_id`` given) or
        every character (``None`` ⇒ enumerate the user's groups, decision L2.6). Each row is
        enriched with ``character_id`` + ``source`` so the admin memory view can attribute
        it (the raw fact only knows its ``group_id``)."""
        groups = await self._resolve_groups(user_id, character_id)
        if not groups:
            return []
        facts = await self._graph.list_facts(groups)
        return [_memory_row(fact) for fact in facts]

    async def clear_all(
        self,
        *,
        user_id: int,
        character_id: str | None = None,
    ) -> int:
        """Forget all memory for a user — one character or every character. Returns the
        number of facts that existed (mem0 parity: count before delete)."""
        groups = await self._resolve_groups(user_id, character_id)
        if not groups:
            return 0
        existing = await self._graph.list_facts(groups)
        for group in groups:
            await self._graph.clear_group(group)
        return len(existing)

    async def delete(self, memory_id: str) -> None:
        """Forget one fact (memory) by its edge id (facts-as-memory, decision D3)."""
        mid = str(memory_id or "").strip()
        if not mid:
            raise ValueError("Memory id is required.")
        await self._graph.delete_facts([mid])

    async def delete_many(self, memory_ids: list[str]) -> int:
        """Forget several memories (fact edges) at once — backs the admin "Clear shown"
        action over the displayed/filtered rows. Blank ids are dropped; missing ids are a
        no-op. Returns the count actually requested."""
        ids = [str(m).strip() for m in (memory_ids or []) if str(m).strip()]
        if not ids:
            return 0
        return await self._graph.delete_facts(ids)

    async def close(self) -> None:
        """Release the underlying graph service. Safe even when the Kuzu driver is shared
        with knowledge — the registry refcount keeps it alive until the last holder
        closes (so closing memory never tears down a driver knowledge still uses)."""
        await self._graph.close()

    async def _resolve_groups(self, user_id: int, character_id: str | None) -> list[str]:
        if character_id:
            return [memory_group_id(user_id, character_id)]
        # All characters for this user → enumerate the user's memory groups (L2.6).
        return await self._graph.list_group_ids(_user_groups_prefix(user_id))
