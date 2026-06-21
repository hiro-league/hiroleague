"""Memory node group — Graphiti recall (search) and conversation-turn ingest (out).

Split out of the old monolithic ``ConversationNodes`` (review §1.5).

- ``memory_search`` — Graphiti recall before context assembly
- ``memory_out`` — emit ``reply.completed`` and ingest the user turn

Both nodes are external-call boundaries (Graphiti API), so both carry retry policies
(see ``_RETRY_POLICIES`` below). ``memory_search`` runs in parallel with the knowledge
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
    emit_for,
    memory_text,
    normalize_reply_content,
)
from ..ledger import graph_logged, observe, substep_scope
from ..node_group import NodeGroup
from ..outcomes import NodeOutcome, emit_outcome
from ..state import GraphState

log = Logger.get("AGENT.GRAPH")


def _memory_results_preview(
    label: str,
    memories: list[dict[str, Any]],
    count: int | None = None,
) -> str:
    total = len(memories) if count is None else count
    snippets = [memory_text(item) for item in memories[:3]]
    snippets = [item for item in snippets if item]
    if snippets:
        return f"{label}: {total} · " + " | ".join(snippets)
    return f"{label}: {total}"


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
        "memory_search": RetryPolicy(max_attempts=2),
        "memory_out": RetryPolicy(max_attempts=2),
    }

    @graph_logged(captures={"usage", "decision"}, on_error="degrade")
    async def memory_search_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        """Bring recent conversation memory (Graphiti) into the turn. Runs after ``trim_history``."""
        text = state.get("user_text") or ""
        observe(input=f"q: {text[:160]}" if text.strip() else "q: <empty>")
        if not text.strip() or self.services.memory is None:
            observe(
                decision=("empty", "disabled" if self.services.memory is None else "no_query"),
                output=(
                    "results: 0; disabled" if self.services.memory is None else "results: 0; no_query"
                ),
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

        # Graphiti memory recall uses only top_k — the shared graph engine owns the rest
        # (sim_min_score / reranker) and bears the query-embedding + search cost.
        search_prefs = memory_prefs.search
        observe(input=f"q: {text[:120]} · top_k={search_prefs.top_k}")

        t0 = time.perf_counter()
        memory_user_id = resolve_memory_user_id(
            data_user_id=state.get("data_user_id"),
            workspace_path=self.services.workspace_path,
        )
        try:
            hits = await self.services.memory.search(
                text,
                user_id=memory_user_id,
                character_id=state.get("character_id", ""),
            )
        except Exception as exc:
            observe(
                fail={"code": "memory_search_failed", "message": str(exc), "decision": "failed"}
            )
            log.warning(
                "memory_search failed - %s",
                state.get("inbound_id", "?"),
                error=str(exc),
            )
            return {}

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        log.info("memory_search retrieved - n=%d", len(hits), elapsed_ms=elapsed_ms)
        emit_outcome(
            writer,
            state,
            NodeOutcome(
                decision=("retrieved" if hits else "empty", str(len(hits))),
                output=_memory_results_preview("results", hits),
                event=(GRAPH_MEMORY_RETRIEVED, {"count": len(hits), "elapsed_ms": elapsed_ms}),
            ),
        )
        return {"retrieved_memories": hits}

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
        await self._store_turn_memory(state, writer, reply_text)
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

        t0 = time.perf_counter()
        memory_user_id = resolve_memory_user_id(
            data_user_id=state.get("data_user_id"),
            workspace_path=self.services.workspace_path,
        )
        memory_run_id = str(state.get("chat_channel_id") or state.get("thread_id") or "")
        # Nest Graphiti's per-episode / per-operation ingest rows under THIS ``memory_out``
        # step (e.g. ``8.1``, ``8.2`` …) instead of letting them restart their own counter —
        # the same ``current_substep`` trick ``knowledge_retrieve_node`` uses. The ingest
        # ledger auto-attaches to the chat run via ``current_run``; passing ``self._ledger_sink``
        # is what turns those rows on. Token cost is priced on those sub-rows (graphiti's
        # default usage sink), so this node's own row carries NO usage — folding it here too
        # would double-count the extraction tokens in the turn total.
        # Anchor the episode to the REAL turn time (routing.timestamp, carried in the
        # inbound envelope), not the ingest wall-clock. Inline ingest makes _now() ≈
        # turn time today, but D4 background ingest would drift; passing the message
        # timestamp keeps temporal ordering/supersession honest regardless of when
        # extraction runs. Serialized as ISO → _parse_reference_time consumes it.
        envelope = state.get("inbound_envelope") or {}
        routing = envelope.get("routing") if isinstance(envelope, dict) else {}
        inbound_ts = routing.get("timestamp") if isinstance(routing, dict) else None
        with substep_scope():
            try:
                result = await self.services.memory.add(
                    # User turn ONLY — the assistant reply (``reply_text``) is intentionally
                    # never ingested (decision D2 / F7 ``conversation`` gate), so the memory
                    # graph can't become a stale echo of its own output.
                    state.get("user_text") or "",
                    user_id=memory_user_id,
                    run_id=memory_run_id,
                    character_id=state.get("character_id", ""),
                    metadata={
                        # Episode uuid == the inbound message id → provenance back to the exact
                        # turn the fact was learned from (decision D5).
                        "message_id": state.get("inbound_id", ""),
                        "thread_id": state.get("thread_id", ""),
                        "channel_id": state.get("chat_channel_id", 0),
                        "source": "conversation",
                        # Real turn time → episode reference_time (see above). Empty ⇒
                        # graphiti_conversation falls back to None ⇒ ingest stamps now.
                        "timestamp": inbound_ts,
                        # A1 fix: anchor the user's facts to their real name. Graphiti extracts the
                        # speaker (token before ":") as the anchor entity, so this turns the generic
                        # "User" hub into a clean named Person. Empty ⇒ graphiti_conversation falls
                        # back to "User" (prior behavior). Configured via memory.user_name.
                        "speaker": (getattr(memory_prefs, "user_name", "") or "").strip(),
                    },
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
        stored_count = result.stored_count
        # ``stored_count == 0`` is a NORMAL outcome — the turn simply had no extractable facts
        # (e.g. "ok thanks") — not a failure. Graphiti raises on real errors, which the
        # try/except above records as ``memory_store_failed``. The extraction token cost shows
        # on the nested Graphiti ingest sub-rows (see above), not on this parent row.
        log.info(
            "✅ memory_out — stored · %s · %dms",
            state.get("inbound_id", "?"),
            elapsed_ms,
            stored=stored_count,
        )
        emit_outcome(
            writer,
            state,
            NodeOutcome(
                decision=("stored", "ok" if stored_count else "no_new_facts"),
                output=_memory_results_preview(
                    "stored",
                    list(getattr(result, "stored_items", ()) or []),
                    stored_count,
                ),
                event=(GRAPH_MEMORY_STORED, {"count": stored_count, "elapsed_ms": elapsed_ms}),
            ),
        )
