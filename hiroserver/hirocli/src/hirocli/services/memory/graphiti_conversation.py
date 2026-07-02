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
    classify_group as _classify_group,
    memory_group_id,
    memory_user_prefix as _user_groups_prefix,
)

if TYPE_CHECKING:
    from hirocli.domain.preferences import KnowledgeGraphTemporalDefault
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


def _admin_fact_row(fact: dict[str, Any]) -> dict[str, Any]:
    """Enrich a raw graph fact with the fields the admin Memories view attributes on —
    ``character_id`` (parsed from the fact's ``group_id``) and ``source`` derived from the
    group's namespace: ``conversation`` for a ``mem_`` group, else the namespace kind
    (``knowledge`` / ``eval`` / ``other``).

    Generalized from the former ``_memory_row`` (which hard-coded ``conversation``) so the
    same enrichment serves BOTH the conversation list (always ``mem_`` groups) and the admin
    group selector, which can point at any partition (``list_facts_in_groups``)."""
    group_id = str(fact.get("group_id", "") or "")
    kind = _classify_group(group_id)
    return {
        **fact,
        "character_id": _character_from_group(group_id),
        "source": "conversation" if kind == "memory" else kind,
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
        temporal_default: "KnowledgeGraphTemporalDefault" = "current",
        event_sink: "GraphEventSink | None" = None,
        group_override: str | None = None,
        extraction_instructions: str = "",
    ) -> None:
        self._graph = graph_service
        self._default_top_k = int(default_top_k)
        # Default temporal lens for recall — follows the admin pref ``graph.temporal_default``
        # (single source of truth across knowledge AND memory legs). The factories in
        # ``services/memory/__init__.py`` snapshot the pref at construction; the agent_manager
        # rebuilds this service whenever ``graph.*`` prefs change, so the snapshot stays fresh.
        # Retired: the previous hardcoded ``"current"`` (former design decision D8) — Settings
        # → Graph → Temporal lens (default) now governs every retrieval leg uniformly.
        self._temporal_default: "KnowledgeGraphTemporalDefault" = temporal_default
        # Optional live-viz sink: when set, each remembered turn streams its new nodes/edges
        # (tagged with the mem_ group) to the admin Graph tab via the DomainEventBus.
        self._event_sink = event_sink
        # Eval-scoped instance (docs/eval-corpus-tracks-design.md §5/§6 — the scoped-service-object):
        # when set, every add/search/clear targets THIS drawer (e.g. ``eval_mem_adam``) instead of
        # deriving ``mem_{user}_{character}`` from the call args. The runtime keeps constructing the
        # unscoped instance (override=None) unchanged, so this is additive — a single binding that
        # redirects the memory eval's data without touching the hot path.
        self._group_override = group_override
        # Optional per-call extraction clause appended to the shared graph nudge for THIS facade's
        # writes (conversation-memory windowing: "attribute facts to the user only" on a two-speaker
        # window). "" ⇒ no clause (current behavior). The chat factory sets it; eval leaves it blank.
        self._extraction_instructions = extraction_instructions

    def _group_for(self, user_id: int, character_id: str) -> str:
        """The drawer this call writes/reads: the eval override when scoped, else the per-
        ``(user, character)`` memory group."""
        return self._group_override or memory_group_id(user_id, character_id)

    async def add(
        self,
        content: str,
        *,
        user_id: int,
        run_id: str,
        character_id: str,
        metadata: dict[str, Any] | None = None,
        ledger_sink: "LedgerSink | None" = None,
        trace_label: str | None = None,
        rebuild_fts: bool = True,
    ) -> MemoryAddResult:
        """Remember the USER half of a turn (decision D2). Returns the facts Graphiti
        learned this turn as ``stored_count`` (facts-as-memory).

        ``ledger_sink`` (the chat turn's sink) makes the write observable in Graph Runs:
        ``ingest_chunks`` records Graphiti's per-episode + per-operation rows, and since the
        chat turn already set ``current_run``, those rows NEST under the active ``memory_out``
        node (the caller sets ``current_substep``) and carry the priced extraction tokens.
        ``usage`` is therefore ``None`` here — token accounting lives on those sub-rows, not
        on a separate ``MemoryUsage`` (per the domain contract).

        ``rebuild_fts`` (default True) rebuilds the Kuzu keyword index after this turn so the fact
        is immediately searchable — the right default for live chat (one turn, then recall). A
        BULK remember loop passes False per turn (avoiding a Kuzu checkpoint per episode, which
        deadlocks against a concurrent graph read) and calls :meth:`flush_search_index` once at
        the end."""
        text = str(content or "").strip()
        if not text:
            return MemoryAddResult(usage=None, stored_count=0)
        meta = dict(metadata or {})
        group = self._group_for(user_id, character_id)
        # Episode uuid == message id ⇒ free provenance back to the stored turn (decision
        # D5). Fall back to inbound_id; empty ⇒ ingest mints no provenance link (still
        # works, just unciteable).
        message_id = str(meta.get("message_id") or meta.get("inbound_id") or "").strip()
        # Windowed ingestion (P2) passes a PRE-RENDERED two-speaker transcript whose lines already
        # carry "[ts] Speaker:" prefixes — so speaker="" tells the ingest layer NOT to re-prefix it.
        # Single-turn callers omit the flag and get the usual user_name anchor (default "User").
        if meta.get("prerendered"):
            speaker = ""
        else:
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
        # Bind role→name in the extraction clause: the body labels speakers with bare names (for A1
        # anchoring), so ``{user}``/``{character}`` must be filled with those SAME names or the
        # extractor has to guess which speaker is the human. Fallbacks match the window body's
        # labels ("User"/"Assistant"). "" ⇒ None ⇒ no clause (eval / non-windowed).
        instructions = self._extraction_instructions or ""
        if instructions:
            instructions = instructions.replace(
                "{user}", str(meta.get("user_name") or "").strip() or "User"
            ).replace(
                "{character}", str(meta.get("character_name") or "").strip() or "Assistant"
            )
        stats = await self._graph.ingest_chunks(
            [episode],
            source_role="conversation",
            group_id=group,
            ledger_sink=ledger_sink,
            event_sink=self._event_sink,  # live viz: stream new facts to the Graph tab
            trace_label=trace_label,  # e.g. graph_ingest_3 for a numbered memory-eval remember turn
            # Windowing (P2): user-only extraction clause for the two-speaker episode, with speaker
            # names bound above; "" ⇒ None ⇒ no change. Blank on the eval facade (corpus stays two-sided).
            extra_extraction_instructions=instructions or None,
            rebuild_fts=rebuild_fts,  # bulk remember defers this → one rebuild at batch end
        )
        stored = int(getattr(stats, "edges_total", 0) or 0)
        log.info(
            "✅ memory — remembered turn · facts=%d · group=%s",
            stored,
            group,
        )
        return MemoryAddResult(usage=None, stored_count=stored)

    async def flush_search_index(self) -> None:
        """Rebuild the keyword (FTS) index once — call after a bulk remember that added turns with
        ``rebuild_fts=False``, so the deferred per-episode rebuilds collapse into a single Kuzu
        checkpoint. Cheap no-op on non-Kuzu backends."""
        await self._graph.rebuild_search_index()

    async def search(
        self,
        query: str,
        *,
        user_id: int,
        character_id: str,
        limit: int | None = None,
        temporal: "KnowledgeGraphTemporalDefault | None" = None,
        k_hop: int | None = None,
        show_expiry: bool = False,
        threshold: float | None = None,
        rerank: bool | None = None,
        metadata_filters: dict[str, Any] | None = None,
        sid: int | None = None,
    ) -> list[dict[str, Any]]:
        """Recall the facts that bear on ``query``, using the admin temporal lens
        (``graph.temporal_default`` — ``current`` hides superseded facts, ``all`` includes
        them). Returns facts-as-memory dicts (``{"memory": dated_fact}``) in the shape
        ``context_assembly.memory_block`` renders.

        ``threshold`` / ``rerank`` are intentionally ignored: those gates are owned by the
        shared graph-engine knobs (``sim_min_score`` / reranker), not re-applied per call
        (decision L2.4). ``metadata_filters`` has no analog in the graph and is ignored."""
        q = str(query or "").strip()
        if not q:
            return []
        group = self._group_for(user_id, character_id)
        top_k = self._default_top_k if limit is None else int(limit)
        # Ledger Graphiti's fact search as a sub-step of the active ``memory_recall`` node:
        # ONE priced ``rerank`` roll-up child (cloud cross-encoder cost), mirroring knowledge's
        # ``graph_expand``. The deep per-stage breakdown lives only in the ``trace`` sidecar.
        # All of this no-ops outside a ledgered chat turn (CLI / admin / tools / tests).
        from hirocli.runtime.agent_graph.ledger import current_entry
        from hirocli.services.knowledge.graph.ledger_tracer import (
            RerankUsage,
            current_rerank_usage,
        )
        from hirocli.services.knowledge.graph.retrieval_trace import (
            RetrievalCapture,
            current_capture,
        )

        # Accumulate cross-encoder rerank usage so the priced ``rerank`` roll-up child carries
        # model + processed tokens. Stays empty for RRF/MMR / local rerankers (no priced child).
        rerank_usage = RerankUsage()
        rerank_token = current_rerank_usage.set(rerank_usage)
        # Deep per-stage retrieval trace (the ``trace`` observability tier) — mirrors knowledge's
        # ``graph_expand`` block: capture activates the re-hosted, traced edge pipeline and we
        # persist the sidecar below. Single pref dial — replaces HIRO_GRAPH_TRACE_RETRIEVAL.
        capture = (
            RetrievalCapture() if self._graph.observability == "trace" else None
        )
        capture_token = current_capture.set(capture) if capture is not None else None
        # Memory recall reads the admin temporal lens by default; per-call overrides support
        # the retrieval-agent tool (agentic-memory P0).
        temporal_lens = temporal if temporal is not None else self._temporal_default
        try:
            expansion = await self._graph.search_chunk_ids(
                q,
                group_id=group,
                num_results=top_k,
                temporal=temporal_lens,
                k_hop=k_hop,
                show_expiry=show_expiry,
            )
        finally:
            current_rerank_usage.reset(rerank_token)
            if capture_token is not None:
                current_capture.reset(capture_token)
        if (entry := current_entry.get()) is not None:
            from hirocli.services.knowledge.graph.retrieval_ledger import flush_graph_expand

            flush_graph_expand(entry, expansion, rerank_usage=rerank_usage)
            if capture is not None and capture.trace is not None:
                from hirocli.services.knowledge.graph.retrieval_trace import (
                    write_trace_sidecar,
                )

                write_trace_sidecar(
                    self._graph.workspace_path,
                    run_id=entry.run_id,
                    step_index=entry.step_index,
                    trace=capture.trace,
                    # Stamp the agentic sub-query id so the eval trajectory UI can open the
                    # pipeline trace for this specific search (None for non-agentic recall).
                    sid=sid,
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
        # Each kind carries structured rows (relevance score + metadata) so the eval recalled-items
        # tables render the right columns per kind: facts add temporal/relationship/source;
        # entities add name/type; episodes add the turn timestamp. ``memory`` stays the dated/plain
        # text so the agent's ``memory_block`` renders unchanged. Older fakes expose only the plain
        # ``*_memories`` strings → fall back to the text-only shape (no score) for each kind.
        fact_rows = tuple(getattr(expansion, "fact_rows", ()) or ())
        node_rows = tuple(getattr(expansion, "node_rows", ()) or ())
        episode_rows = tuple(getattr(expansion, "episode_rows", ()) or ())
        if fact_rows:
            hits: list[dict[str, Any]] = [dict(row) for row in fact_rows]
        else:
            hits = [{"memory": fact, "kind": "fact"} for fact in expansion.facts]
        if node_rows:
            hits.extend(dict(row) for row in node_rows)
        else:
            hits.extend({"memory": summary, "kind": "entity"} for summary in node_memories)
        if episode_rows:
            hits.extend(dict(row) for row in episode_rows)
        else:
            hits.extend({"memory": body, "kind": "episode"} for body in episode_memories)
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
        return [_admin_fact_row(fact) for fact in facts]

    async def list_facts_in_groups(self, group_ids: list[str]) -> list[dict[str, Any]]:
        """List facts for explicit partitions — backs the admin Memories group selector,
        which can point at ANY group (memory / knowledge / eval), not just this user's
        conversation groups. Read-only; each row is enriched with ``character_id`` + a
        namespace-derived ``source`` so the admin view can attribute it. Blank ids dropped;
        empty input returns ``[]`` (never an all-groups scan)."""
        groups = [str(g).strip() for g in (group_ids or []) if str(g).strip()]
        if not groups:
            return []
        facts = await self._graph.list_facts(groups)
        return [_admin_fact_row(fact) for fact in facts]

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

    async def clear_groups(self, group_ids: list[str]) -> int:
        """Wipe whole partitions — backs the admin "Clear group" action (memories redesign).

        Unlike :meth:`delete_many` (which forgets specific fact edges), this drops each
        group's ENTIRE contents via :meth:`GraphitiMemoryService.clear_group` — facts +
        entities + episodes + communities — so a cleared group is truly empty (and drops
        out of the group selector, since it's derived from the Episodic table). Callers
        (the route) validate the ids against the group grammar first; blank ids are dropped
        and empty input is a no-op. Returns the total episodes removed."""
        groups = [str(g).strip() for g in (group_ids or []) if str(g).strip()]
        if not groups:
            return 0
        total = 0
        for group in groups:
            total += await self._graph.clear_group(group)
        return total

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
        # Eval-scoped instance: every list/clear targets the single override drawer.
        if self._group_override:
            return [self._group_override]
        if character_id:
            return [memory_group_id(user_id, character_id)]
        # All characters for this user → enumerate the user's memory groups (L2.6).
        return await self._graph.list_group_ids(_user_groups_prefix(user_id))
