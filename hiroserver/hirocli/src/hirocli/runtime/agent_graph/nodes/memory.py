"""Memory node group — Graphiti recall (search) and conversation-turn ingest (out).

Split out of the old monolithic ``ConversationNodes`` (review §1.5).

- ``memory_recall`` — Graphiti recall before context assembly
- ``memory_out`` — emit ``reply.completed`` and ingest the user turn

Both nodes are external-call boundaries (Graphiti API), so both carry retry policies
(see ``_RETRY_POLICIES`` below). ``memory_recall`` runs in parallel with the knowledge
fan-out off ``trim_history``; ``memory_out`` runs after ``call_model``/tools.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from hiro_commons.log import Logger
from langgraph.types import RetryPolicy, StreamWriter

from ....domain.memory import resolve_memory_user_id
from ..events import (
    GRAPH_ERROR,
    GRAPH_MEMORY_RETRIEVED,
    GRAPH_MEMORY_STORED,
    GRAPH_REPLY_COMPLETED,
)
from ..graph_kit import (
    IDENTITY_PEER_KEYS,
    emit,
    normalize_reply_content,
)
from ..ledger import current_entry, graph_logged, observe, record_child, substep_scope
from ..node_group import NodeGroup
from ..outcomes import NodeOutcome, emit_outcome
from ..state import GraphState

log = Logger.get("AGENT.GRAPH")


def _serialize_knowledge_sources(sources: list[Any]) -> list[dict[str, Any]]:
    """Compact, JSON-safe view of KnowledgeSource for the reply event + persisted metadata.

    Carries just what a source-list UI needs; the bracket [n] in the reply text maps to ``ref``.
    Lives here (not in ``knowledge.py``) because the only caller is ``memory_out``'s reply event.
    """
    out: list[dict[str, Any]] = []
    for source in sources:
        out.append(
            {
                "ref": getattr(source, "ref", None),
                "title": getattr(source, "title", ""),
                "heading_path": getattr(source, "heading_path", None),
                "source_uri": getattr(source, "source_uri", ""),
                "document_id": getattr(source, "document_id", ""),
                "score": getattr(source, "score", None),
            }
        )
    return out


class MemoryNodes(NodeGroup):
    """Memory recall + ingest — constructed from ``AgentServices`` only."""

    _RETRY_POLICIES = {
        "memory_recall": RetryPolicy(max_attempts=2),
        "memory_out": RetryPolicy(max_attempts=2),
    }

    def _recall_model_cache(self):
        """The shared, cross-turn recall-model cache (C2), lazily created on ``AgentServices``.

        Lives on ``services`` (a long-lived singleton) so it survives across turns and is shared by
        every compiled chat graph — the recall model is independent of the chat model/character.
        """
        from ....services.memory.models import MemoryRetrievalModelCache

        cache = self.services.memory_retrieval_models
        if cache is None:
            cache = MemoryRetrievalModelCache()
            self.services.memory_retrieval_models = cache
        return cache

    @graph_logged(captures={"usage", "decision"}, on_error="degrade")
    async def memory_recall_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        """Agentic memory recall (the Graphiti retrieval loop) before context assembly.

        Phase 2 (memory-eval-vs-chat-parity): replaces the pre-P2 single-shot ``memory.search()``
        with the shared, history-aware, abstain-allowed loop (``MemoryRetriever`` over
        ``memory.retrieval.*`` config). Produces the recalled rows AND a draft grounding note
        (``memory_draft``) for the persona (consumed in Phase 4). Runs after ``trim_history`` so the
        history it sees is already bounded to ``chat.max_messages``.
        """
        text = state.get("user_text") or ""
        observe(input=f"q: {text[:160]}" if text.strip() else "q: <empty>")

        memory = self.services.memory
        if not text.strip() or memory is None:
            observe(
                decision=("empty", "disabled" if memory is None else "no_query"),
                output="results: 0; disabled" if memory is None else "results: 0; no_query",
            )
            return {}

        memory_prefs = self.prefs.memory()
        if not bool(getattr(memory_prefs, "enabled", False)):
            observe(decision=("empty", "disabled"), output="results: 0; disabled")
            return {}
        # Independent per-direction toggle: skip retrieval when memory search is off.
        if not bool(getattr(getattr(memory_prefs, "search", None), "enabled", True)):
            observe(decision=("empty", "search_disabled"), output="results: 0; search disabled")
            return {}

        prefs = self.prefs.current
        if prefs is None:
            observe(decision=("empty", "no_prefs"), output="results: 0; prefs unavailable")
            return {}

        # Lazy imports keep the retrieval-loop deps off this module's base import path.
        from ....domain.preferences import resolve_chat_retrieval_agent_prompt
        from ....services.memory.agent import (
            MemoryRetriever,
            accumulated_item_to_recall_row,
            present_accumulator,
        )
        from ....services.memory.agent.agent_trace import (
            build_recall_ledger_substeps,
            format_recall_items_preview,
            summarize_agent_transcript,
            write_agent_recall_result,
            write_agent_retrieval_trace,
        )

        # Under `trace`, attribute the loop's LLM cost PER TURN (priced sub-rows) instead of one
        # aggregate on this node, and persist the loop sidecars. `per_step_usage` follows this flag so
        # the parent node doesn't ALSO carry the tokens (double-count) — see run_retrieval.
        trace_on = getattr(prefs.graph, "observability", "ledger") == "trace"

        # Chat retrieval config (memory.retrieval.*, Phase 1): caps + prompt + model.
        limits = prefs.memory.retrieval.limits
        _prompt_id, prompt_text = resolve_chat_retrieval_agent_prompt(prefs)
        # C2: the recall model is cached across turns (rebuilt only when its spec changes) instead of
        # reconstructing the provider client every message — see MemoryRetrievalModelCache.
        model, model_id = self._recall_model_cache().get(
            prefs, self.services.workspace_path, credential_store=self.services.credentials
        )
        if model is None:
            observe(decision=("empty", "no_model"), output="results: 0; no retrieval model")
            return {}

        memory_user_id = resolve_memory_user_id(
            data_user_id=state.get("data_user_id"),
            workspace_path=self.services.workspace_path,
        )
        # Identities → the loop phrases queries with the real names (memory anchors facts to the
        # speaker's real name, so "{user}'s wife" hits far better than "the user's wife"). Same
        # resolution ingest uses (memory.user_name A1 anchor + the character display name); the
        # assistant is marked as the AI in the prompt to avoid same-name collisions.
        from ....domain.character import get_character_name

        user_name = (getattr(memory_prefs, "user_name", "") or "").strip()
        agent_name = get_character_name(self.services.workspace_path, state.get("character_id", ""))
        # History = the trimmed prior turns (bounded by chat.max_messages in trim_history). The
        # current user turn isn't in ``messages`` yet (it's ``user_text``, appended later by
        # context_build) — so this is exactly the anaphora context the loop's turn 1 resolves against.
        history = list(state.get("messages") or [])

        t0 = time.perf_counter()
        try:
            result = await MemoryRetriever.retrieve(
                text,
                memory=memory,
                limits=limits,
                prompt_text=prompt_text,
                model=model,
                model_id=model_id,
                user_id=memory_user_id,
                character_id=state.get("character_id", ""),
                history=history,
                allow_abstain=True,
                user_name=user_name,
                agent_name=agent_name,
                per_step_usage=trace_on,
            )
        except Exception as exc:
            observe(
                fail={"code": "memory_recall_failed", "message": str(exc), "decision": "failed"}
            )
            log.warning(
                "❌ memory_recall — loop failed · %s",
                state.get("inbound_id", "?"),
                error=str(exc),
                exc_info=True,
            )
            return {}

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        rows = [
            accumulated_item_to_recall_row(item) for item in present_accumulator(result.accumulator)
        ]
        draft = (result.answer_text or "").strip() or None
        n = len(rows)

        # G3: persist the loop transcript sidecar (turns/sub-queries) AND the recalled rows + draft
        # answer companion — trace tier only, best-effort. The companion mirrors what eval stores in
        # row_json so the Graph-Runs detail dialog renders the SAME Overview + Facts/Entities/Episodes
        # tables (with counts) a memory-eval row shows (a chat recall has no eval_results.db row).
        if trace_on:
            entry = current_entry.get()
            if entry is not None:
                if result.transcript:
                    write_agent_retrieval_trace(
                        self.services.workspace_path,
                        run_id=str(entry.run_id),
                        slot=str(entry.step_index),
                        events=result.transcript,
                    )
                write_agent_recall_result(
                    self.services.workspace_path,
                    run_id=str(entry.run_id),
                    slot=str(entry.step_index),
                    recalled=rows,
                    answer=draft or "",
                )
                # Per-turn / per-search sub-nodes (4.1, 4.2 …) under this memory_recall step: one
                # priced memory/recall_turn per LLM turn + one memory/search per sub-query, so the
                # loop's internals are inspectable in the Graph-Runs node table (not only the
                # trajectory dialog). Pure over the transcript; children carry the per-turn cost
                # (parent carries none — per_step_usage above).
                for spec in build_recall_ledger_substeps(result.transcript, model_id=model_id):
                    record_child(**spec)

        # G2: decision distinguishes recalled / abstained (the loop chose NOT to search) / errored /
        # empty — so "why no memory this turn" is answerable in Graph Runs (observability by design).
        # decision_detail carries the STATS (facts/turns/searches); output_preview carries the REAL
        # recalled facts (numbered, scored) — the useful content, not counts.
        summary = summarize_agent_transcript(result.transcript)
        if n:
            decision = ("retrieved", f"{n}facts/{summary.agent_turns}turns/{summary.searches}searches")
            preview = format_recall_items_preview(rows, max_items=5)
        elif summary.searches == 0:
            decision = ("abstained", "no_recall_needed")
            preview = "abstained — no memory needed this turn"
        elif getattr(result, "error_count", 0):
            decision = ("empty", f"{result.error_count}errors")
            preview = f"recall emptied by {result.error_count} search error(s)"
        else:
            decision = ("empty", "0")
            preview = "nothing recalled"
        log.info(
            "✅ memory_recall — %s · rows=%d · searches=%d · draft=%s",
            state.get("inbound_id", "?"),
            n,
            summary.searches,
            "yes" if draft else "no",
            elapsed_ms=elapsed_ms,
        )
        emit_outcome(
            writer,
            state,
            NodeOutcome(
                decision=decision,
                output=preview,
                event=(GRAPH_MEMORY_RETRIEVED, {"count": n, "elapsed_ms": elapsed_ms}),
            ),
        )
        return {"retrieved_memories": rows, "memory_draft": draft}

    @graph_logged(captures={"usage", "decision"}, on_error="raise")
    async def memory_out_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        """Finalize the reply text and emit ``reply.completed``.

        Surfaces the normalized reply text, announces it to subscribers, then stores the
        user/assistant turn in long-term memory when enabled.
        """
        msgs = state.get("messages", []) or []
        reply_text = ""
        if msgs:
            reply_text = normalize_reply_content(msgs[-1].content)

        observe(input=f"user: {state.get('user_text') or ''} · assistant: {reply_text}")

        if not reply_text:
            observe(output="error: empty_reply")
            log.warning(
                "⚠️ memory_out — empty reply · %s",
                state.get("inbound_id", "?"),
            )
            emit(
                writer,
                GRAPH_ERROR,
                {
                    "inbound_id": state.get("inbound_id", ""),
                    "node": "memory_out",
                    "error": "empty_reply",
                },
            )
            return {"reply_text": None}

        reply_id = f"reply-{uuid.uuid4()}"
        log.info(
            "✅ reply — %s · len=%d",
            state.get("inbound_id", "?"),
            len(reply_text),
        )
        emit_outcome(
            writer,
            state,
            NodeOutcome(
                event=(
                    GRAPH_REPLY_COMPLETED,
                    {
                        "thread_id": state.get("thread_id", ""),
                        "reply_text": reply_text,
                        "reply_id": reply_id,
                        "request_voice_reply": bool(state.get("request_voice_reply", False)),
                        "knowledge_sources": self._reply_knowledge_sources(state),
                    },
                ),
                event_identity_keys=IDENTITY_PEER_KEYS,
            ),
        )
        await self._store_turn_memory(state, writer, reply_text, reply_id)
        return {"reply_text": reply_text, "reply_id": reply_id}

    def _reply_knowledge_sources(self, state: GraphState) -> list[dict[str, Any]]:
        """Serialized knowledge sources to attach to the reply — only when chat citations are on."""
        if not self.prefs.cite_sources():
            return []
        return _serialize_knowledge_sources(state.get("knowledge_sources") or [])

    async def _store_turn_memory(
        self,
        state: GraphState,
        writer: StreamWriter,
        reply_text: str,
        reply_id: str,
    ) -> None:
        memory_prefs = self.prefs.memory()
        if self.services.memory is None or not bool(getattr(memory_prefs, "enabled", False)):
            observe(decision=("skipped", "disabled"), output="stored: 0; disabled")
            return
        # Independent per-direction toggle: skip storage when memory extraction is off (read-only).
        if not bool(getattr(getattr(memory_prefs, "extraction", None), "enabled", True)):
            observe(
                decision=("skipped", "extraction_disabled"),
                output="stored: 0; extraction disabled",
            )
            return

        # Windowed batch ingestion (docs/memory-eval-vs-chat-parity.md → "Ingestion — implementation
        # design"): rather than write this one user turn, accumulate N exchanges per conversation and
        # ingest them as ONE two-speaker episode (agent turns as context, user-only extraction). The
        # controller reads the pending turns from the durable message store and splices the current
        # reply, so it needs a real channel to window over.
        channel_id = int(state.get("chat_channel_id") or 0)
        if channel_id <= 0:
            observe(decision=("skipped", "no_channel"), output="stored: 0; no channel")
            return

        # Lazy imports keep the windowing/data.db paths off this module's base import path.
        from hiro_commons.timestamps import utc_iso, utc_now

        from ....domain.character import get_character_name
        from ....services.memory.windowed_ingest import ingest_pending_windows

        t0 = time.perf_counter()
        memory_user_id = resolve_memory_user_id(
            data_user_id=state.get("data_user_id"),
            workspace_path=self.services.workspace_path,
        )
        memory_run_id = str(state.get("chat_channel_id") or state.get("thread_id") or "")
        character_id = state.get("character_id", "")
        ext = memory_prefs.extraction
        # Nest Graphiti's per-episode / per-operation ingest rows under THIS ``memory_out`` step:
        # ``substep_scope`` sets ``current_substep``, and the graph-ingest ledger borrows THIS node's
        # run id from ``current_entry`` (a chat turn has no ``current_run`` accumulator) so its rows
        # land as sub-rows of ``memory_out`` in the chat run — instead of spawning a standalone
        # ``knowledge_graph_ingest`` run the Graph Runs page can't render. ``self._ledger_sink``
        # (passed inside the controller) turns those rows on. Token cost prices on those sub-rows, so
        # this node's own row carries no usage.
        with substep_scope():
            try:
                result = await ingest_pending_windows(
                    self.services.memory,
                    workspace_path=self.services.workspace_path,
                    channel_id=channel_id,
                    user_id=memory_user_id,
                    run_id=memory_run_id,
                    character_id=character_id,
                    # Speaker labels: the user_name pref (A1 anchor) + the character's display name.
                    user_name=(getattr(memory_prefs, "user_name", "") or "").strip(),
                    character_name=get_character_name(self.services.workspace_path, character_id),
                    window_turns=int(getattr(ext, "window_turns", 4)),
                    session_gap_minutes=int(getattr(ext, "session_gap_minutes", 120)),
                    chunk_min_tokens=int(getattr(ext, "chunk_min_tokens", 1000)),
                    # Splice the current reply so the current exchange completes with no lag — its
                    # external_id becomes ``reply_id`` when persisted downstream (reply.completed).
                    current_reply_id=reply_id,
                    current_reply_text=reply_text,
                    current_reply_at=utc_iso(utc_now()),
                    ledger_sink=self._ledger_sink,
                )
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                observe(
                    fail={"code": "memory_store_failed", "message": str(exc), "decision": "failed"}
                )
                log.warning(
                    "❌ memory_out — store failed · %s",
                    state.get("inbound_id", "?"),
                    error=str(exc),
                    elapsed_ms=elapsed_ms,
                    exc_info=True,
                )
                return

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        stored_count = result.facts
        # ``stored_count == 0`` is a NORMAL outcome — the window may still be accumulating (fewer
        # than N exchanges pending), or the flushed turns had no extractable facts. Not a failure
        # (Graphiti raises on real errors, caught above). Extraction token cost shows on the nested
        # Graphiti ingest sub-rows, not this parent row.
        # Trigger note (tuning): which flush trigger(s) fired this turn, e.g. "· 1 window: count".
        window_note = (
            f" · {result.windows} window(s): {', '.join(result.triggers)}" if result.triggers else ""
        )
        log.info(
            "✅ memory_out — windowed ingest · %s · %dms",
            state.get("inbound_id", "?"),
            elapsed_ms,
            stored=stored_count,
            windows=result.windows,
        )
        emit_outcome(
            writer,
            state,
            NodeOutcome(
                decision=("stored", "ok" if stored_count else "no_new_facts"),
                output=f"stored: {stored_count}{window_note}",
                event=(
                    GRAPH_MEMORY_STORED,
                    {
                        "count": stored_count,
                        "elapsed_ms": elapsed_ms,
                        # Flush-trigger telemetry for the Graph tab / tuning.
                        "windows": result.windows,
                        "triggers": list(result.triggers),
                    },
                ),
            ),
        )
