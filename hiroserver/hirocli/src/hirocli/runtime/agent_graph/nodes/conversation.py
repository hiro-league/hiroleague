"""Conversation node group — trim, memory, knowledge, LLM, tools, TTS, finalize."""

from __future__ import annotations

import json
import time
import uuid
from typing import TYPE_CHECKING, Any

from hiro_commons.log import Logger
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.types import StreamWriter

from ....domain.memory import resolve_memory_user_id
from ..context_assembly import (
    ContextAssembler,
    citation_block,
    instructions_block,
    knowledge_block,
    memory_block,
)
from ..config import ChatGraphConfig
from ..events import (
    GRAPH_ERROR,
    GRAPH_LLM_USAGE,
    GRAPH_MEMORY_RETRIEVED,
    GRAPH_MEMORY_STORED,
    GRAPH_REPLY_COMPLETED,
    GRAPH_RUN_COMPLETED,
    GRAPH_RUN_FAILED,
    GRAPH_TOOL_COMPLETED,
    GRAPH_TTS_COMPLETED,
)
from ..graph_kit import (
    KNOWLEDGE_PREVIEW_MAX,
    emit,
    knowledge_results_rows,
    llm_usage_payload,
    normalize_reply_content,
)
from ..ledger import graph_logged, observe, record_child, substep_scope
from ..node_group import NodeGroup
from .tts_support import build_tts_usage, metered_text
from ..state import GraphState, ReplyAudio
from ._helpers import _error_slug

if TYPE_CHECKING:
    from ..services import AgentServices

log = Logger.get("AGENT.GRAPH")

_AGENT_TOOL_ARGS_MAX = 2000
_AGENT_TOOL_RESULT_MAX = 4000

def _llm_decision(message: AIMessage) -> tuple[str, str]:
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        return "tool_call", _tool_call_name(tool_calls[0])
    content = normalize_reply_content(message.content)
    if content.strip():
        return "text_reply", "ok"
    return "empty", "no_content"




def _serialize_knowledge_sources(sources: list[Any]) -> list[dict[str, Any]]:
    """Compact, JSON-safe view of KnowledgeSource for the reply event + persisted metadata.

    Carries just what a source-list UI needs; the bracket [n] in the reply text maps to ``ref``.
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




def _format_history(messages: list[AnyMessage], *, limit: int = 6) -> str:
    """Format the last ``limit`` prior turns as 'Role: text' lines for the knowledge rewrite node.

    Called at ``knowledge_retrieve`` time, before the new user turn is appended, so this is the
    prior conversation only — exactly the context needed to resolve references in the query.
    """
    lines: list[str] = []
    for message in messages[-limit:]:
        if isinstance(message, HumanMessage):
            role = "User"
        elif isinstance(message, AIMessage):
            role = "Assistant"
        else:
            continue
        text = normalize_reply_content(message.content).strip()
        if text:
            lines.append(f"{role}: {text}")
    return "\n".join(lines)




def _memory_results_preview(
    label: str,
    memories: list[dict[str, Any]],
    count: int | None = None,
) -> str:
    total = len(memories) if count is None else count
    snippets = [_memory_text(item) for item in memories[:3]]
    snippets = [item for item in snippets if item]
    if snippets:
        return f"{label}: {total} · " + " | ".join(snippets)
    return f"{label}: {total}"




def _memory_text(item: dict[str, Any]) -> str:
    text = (
        item.get("memory")
        or item.get("text")
        or item.get("content")
        or item.get("data")
        or item.get("value")
        or ""
    )
    return " ".join(str(text or "").split())




def _last_human_message_preview(messages: list[AnyMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return normalize_reply_content(message.content)
    return normalize_reply_content(messages[-1].content) if messages else ""




def _tool_calls_preview(tool_calls: list[dict[str, Any]]) -> str:
    if not tool_calls:
        return "reply: <empty>"
    names = [_tool_call_name(call) or "unknown" for call in tool_calls[:4]]
    return f"tool_calls: {len(tool_calls)}; " + ", ".join(names)




def _tool_input_preview(tool_name: str, args: dict[str, Any]) -> str:
    try:
        arg_text = json.dumps(args, ensure_ascii=False, default=str)
    except TypeError:
        arg_text = str(args)
    return f"{tool_name or 'unknown'} args: {arg_text}"


# Bounded strings for admin message metadata (separate from ledger previews).
_AGENT_TOOL_ARGS_MAX = 2000
_AGENT_TOOL_RESULT_MAX = 4000




def _tool_args_one_line(args: dict[str, Any], *, max_len: int = _AGENT_TOOL_ARGS_MAX) -> str:
    try:
        text = json.dumps(args, ensure_ascii=False, default=str, separators=(",", ":"))
    except TypeError:
        text = str(args)
    compact = " ".join(text.split())
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3] + "..."




def _tool_result_bounded(content: str, *, max_len: int = _AGENT_TOOL_RESULT_MAX) -> str:
    text = str(content or "")
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."




def _trim_chat_history(messages: list[AnyMessage], limit: int) -> list[AnyMessage]:
    """Return a bounded chat suffix that does not start inside a tool exchange."""
    if limit <= 0:
        return []
    keep = list(messages[-limit:])
    while keep and not isinstance(keep[0], HumanMessage):
        keep.pop(0)
    return keep




def _tool_call_id(call: dict[str, Any]) -> str:
    return str(call.get("id") or "")




def _tool_call_name(call: dict[str, Any]) -> str:
    return str(call.get("name") or "")




def _tool_call_args(call: dict[str, Any]) -> dict[str, Any]:
    args = call.get("args") or {}
    return args if isinstance(args, dict) else {}




def _tool_result_content(result: Any) -> str:
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except TypeError:
        return str(result)



class ConversationNodes(NodeGroup):
    """Model-bound conversation nodes — constructed per ``build(config)``."""

    def __init__(self, services: "AgentServices", config: ChatGraphConfig) -> None:
        super().__init__(services)
        self._model_id = config.model_id
        self._system_prompt = config.system_prompt
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens
        self._thinking = config.thinking
        self._tools = config.tools
        self._model = config.model
        self._bound = config.model.bind_tools(config.tools) if config.tools else config.model
        self._tools_by_name = {getattr(t, "name", ""): t for t in config.tools}
        self._assembler = ContextAssembler()

    async def trim_history_node(self, state: GraphState) -> dict[str, Any]:
        """Trim chat history to the latest ``chat.max_messages`` turns.

        Split out of the old ``memory_in`` node so it runs *before* the parallel
        memory + knowledge branches: both consume the same trimmed window (knowledge's
        history-aware query rewrite must see exactly what memory sees).
        """
        messages: list[AnyMessage] = list(state.get("messages", []) or [])
        limit = self.prefs.history_window()
        keep = _trim_chat_history(messages, limit)
        if keep == messages:
            return {}
        from langchain_core.messages import RemoveMessage
        from langgraph.graph.message import REMOVE_ALL_MESSAGES

        log.info("trim_history - before=%d after=%d", len(messages), len(keep))
        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *keep]}


    @graph_logged(captures={"usage", "decision"})
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
        observe(
            decision=("retrieved" if hits else "empty", str(len(hits))),
            output=_memory_results_preview("results", hits),
        )
        log.info("memory_search retrieved - n=%d", len(hits), elapsed_ms=elapsed_ms)
        emit(
            writer,
            GRAPH_MEMORY_RETRIEVED,
            {
                "inbound_id": state.get("inbound_id", ""),
                "chat_channel_id": state.get("chat_channel_id", 0),
                "character_id": state.get("character_id", ""),
                "count": len(hits),
                "elapsed_ms": elapsed_ms,
            },
        )
        return {"retrieved_memories": hits}


    def knowledge_fanout(self, state: GraphState) -> list[str]:
        """Fan out from ``trim_history`` to the parallel context branches.

        ``memory_search`` always runs; ``knowledge_retrieve`` is added only when a knowledge
        subgraph is wired and the per-message toggle is on (default on). Both join at
        ``context_build``.
        """
        targets = ["memory_search"]
        if self.services.knowledge_subgraph is not None and bool(state.get("knowledge_enabled", True)):
            targets.append("knowledge_retrieve")
        return targets


    @graph_logged(captures={"decision"})
    async def knowledge_retrieve_node(
        self, state: GraphState, writer: StreamWriter
    ) -> dict[str, Any]:
        """Run the knowledge retrieval subgraph and map context + sources into chat state.

        Invoked with no ledger run of its own, so its ``knowledge/*`` node rows fold into the
        chat turn. Any failure degrades gracefully — the turn still answers without knowledge.
        """
        if self.services.knowledge_subgraph is None:
            observe(decision=("skipped", "no_subgraph"), output="sources: 0; no_subgraph")
            return {}
        user_text = (state.get("user_text") or "").strip()
        if not user_text:
            observe(decision=("empty", "no_user_text"), output="sources: 0; no_user_text")
            return {}
        observe(input=f"query: {user_text[:160]}")

        retrieval = self.prefs.current.knowledge.retrieval
        sub_input: dict[str, Any] = {
            "query": user_text,
            "history": _format_history(list(state.get("messages") or [])),
            "rewrite": True,
            "filters": self._knowledge_scope_filters(state),
            "top_k": retrieval.top_k,
            "min_score": retrieval.min_score,
            "inbound_id": state.get("inbound_id", ""),
            "chat_channel_id": state.get("chat_channel_id", 0),
            "character_id": state.get("character_id", ""),
            "user_id": str(state.get("data_user_id") or ""),
        }
        # Number the retrieval subgraph's ``knowledge/*`` rows as sub-steps of this node (e.g. ``4.1``)
        # so they sort under it in the ledger instead of restarting their own step counter.
        with substep_scope():
            try:
                out = await self.services.knowledge_subgraph.ainvoke(sub_input)
            except Exception as exc:
                log.warning(
                    "⚠️ knowledge_retrieve failed - %s",
                    state.get("inbound_id", "?"),
                    error=str(exc),
                    exc_info=True,
                )
                observe(
                    fail={
                        "code": "knowledge_retrieve_failed",
                        "message": str(exc),
                        "decision": "failed",
                    }
                )
                return {}

        sources = list(out.get("sources") or [])
        context = out.get("context") or ""
        if sources:
            score_source = str(getattr(sources[0], "score_source", "") or "").strip()
            head = f"{len(sources)} src" + (f" ({score_source})" if score_source else "")
            observe(
                decision=("retrieved", str(len(sources))),
                output=f"{head} · {knowledge_results_rows(sources)}",
                output_max_len=KNOWLEDGE_PREVIEW_MAX,
            )
        else:
            observe(decision=("empty", str(len(sources))), output="0 src")
        return {"knowledge_context": context, "knowledge_sources": sources}


    def _knowledge_scope_filters(self, state: GraphState) -> dict[str, Any]:
        """Owner/category scope for chat retrieval, derived server-side (never from the LLM).

        v1: all owners visible (system + character + user) → no filter. Tightening to a
        per-character/per-user policy is a later step.
        """
        return {}


    async def context_build_node(self, state: GraphState) -> dict[str, Any]:
        """Append the new user turn — and ONLY the user turn — to the (trimmed) history.

        Memory / knowledge / citation context is assembled ephemerally by ``compose_context`` into
        ``turn_context`` and injected by ``call_model`` into the current user turn; it must never
        enter ``messages`` (durable history stays clean across turns). See
        ``docs/context-assembly.md``.
        """
        text = state.get("user_text")
        if not text:
            # No usable input — leave messages untouched; call_model will short-circuit.
            return {}
        return {"messages": [HumanMessage(content=text)]}


    def should_continue(self, state: GraphState) -> str:
        """Tools-loop conditional edge: route to ``tools`` when the LLM asked for one."""
        msgs = state.get("messages", []) or []
        if not msgs:
            return "memory_out"
        last = msgs[-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return "memory_out"


    @graph_logged(captures={"usage", "decision"})
    async def memory_out_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        """Finalize the reply text and emit ``reply.completed``.

        This node surfaces the normalized reply text, announces it to subscribers,
        then stores the user/assistant turn in long-term memory when enabled.
        """
        msgs = state.get("messages", []) or []
        reply_text = ""
        if msgs:
            reply_text = normalize_reply_content(msgs[-1].content)

        observe(
            input=f"user: {state.get('user_text') or ''} · assistant: {reply_text}"
        )

        if not reply_text:
            observe(output="error: empty_reply")
            log.warning(
                "⚠️ memory_out — empty reply · %s",
                state.get("inbound_id", "?"),
            )
            emit(
            writer, GRAPH_ERROR, {
                "inbound_id": state.get("inbound_id", ""),
                "node": "memory_out",
                "error": "empty_reply",
            })
            return {"reply_text": None}

        reply_id = f"reply-{uuid.uuid4()}"
        log.info(
            "✅ reply — %s · len=%d",
            state.get("inbound_id", "?"), len(reply_text),
        )
        emit(
            writer,
            GRAPH_REPLY_COMPLETED,
            {
                "inbound_id": state.get("inbound_id", ""),
                "chat_channel_id": state.get("chat_channel_id", 0),
                "thread_id": state.get("thread_id", ""),
                "reply_text": reply_text,
                "reply_id": reply_id,
                "request_voice_reply": bool(state.get("request_voice_reply", False)),
                "knowledge_sources": self._reply_knowledge_sources(state),
            },
        )
        await self._store_turn_memory(state, writer, reply_text)
        return {"reply_text": reply_text, "reply_id": reply_id}


    def tts_gate(self, state: GraphState) -> str:
        """Decide whether to enter the TTS branch after the reply completes."""
        if not state.get("reply_text"):
            return "finalize"
        if not state.get("request_voice_reply"):
            return "finalize"
        if self.services.tts is None or not self.services.tts.is_available():
            return "finalize"
        return "tts"


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
        observe(
            decision=("stored", "ok" if stored_count else "no_new_facts"),
            output=_memory_results_preview(
                "stored",
                list(getattr(result, "stored_items", ()) or []),
                stored_count,
            ),
        )
        log.info(
            "✅ memory_out — stored · %s · %dms",
            state.get("inbound_id", "?"),
            elapsed_ms,
            stored=stored_count,
        )
        emit(
            writer,
            GRAPH_MEMORY_STORED,
            {
                "inbound_id": state.get("inbound_id", ""),
                "chat_channel_id": state.get("chat_channel_id", 0),
                "character_id": state.get("character_id", ""),
                "count": stored_count,
                "elapsed_ms": elapsed_ms,
            },
        )


    def _resolve_voice(self, state: GraphState, writer: StreamWriter):
        """Load character + resolve TTS voice; return resolved voice or None after observe/emit."""
        from ....domain.character import load_character_from_disk
        from ....domain.preferences import resolve_character_voice

        inbound_id = state.get("inbound_id", "")
        try:
            ch = load_character_from_disk(
                self.services.workspace_path, state.get("character_id", "")
            )
        except FileNotFoundError as exc:
            observe(
                decision=("skipped_no_voice", "character_missing"),
                skipped="character_missing",
                output="audio: skipped character_missing",
            )
            emit(
                writer,
                GRAPH_ERROR,
                {"inbound_id": inbound_id, "node": "tts", "error": str(exc)},
            )
            return None

        prefs = self.prefs.current
        resolved = resolve_character_voice(
            ch.voice_models,
            prefs,
            self.services.workspace_path,
            credential_store=self.services.credentials,
            tts_instructions=ch.tts_instructions,
            tts_voice_by_provider=dict(ch.tts_voice_by_provider),
        )
        if resolved is None:
            observe(
                decision=("skipped_no_voice", "voice_unresolved"),
                skipped="voice_unresolved",
                output="audio: skipped voice_unresolved",
            )
            log.warning(
                "⚠️ tts — %s · no_voice_resolved (set character voice_models / llm.default_tts)",
                inbound_id,
            )
            emit(
                writer,
                GRAPH_ERROR,
                {"inbound_id": inbound_id, "node": "tts", "error": "no_voice_resolved"},
            )
            return None
        return resolved

    @graph_logged(captures={"usage", "decision"})
    async def tts_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        """Synthesize speech for ``reply_text`` and emit ``tts.completed``.

        Audio bytes are passed through the event payload as base64 (the same
        wire shape ``message.voiced`` already used today). The persistence
        subscriber on the CommManager side writes the attachment row and the
        media file from the event.
        """
        text = state.get("reply_text") or ""
        inbound_id = state.get("inbound_id", "")
        observe(input=f"text: {text}" if text else "text: <empty>")
        if not text:
            observe(
                decision=("skipped_no_text", "empty"),
                skipped="empty",
                output="audio: skipped empty",
            )
            return {}

        resolved = self._resolve_voice(state, writer)
        if resolved is None:
            return {}

        t0 = time.perf_counter()
        try:
            result = await self.services.tts.synthesize(  # type: ignore[union-attr]
                text,
                model=resolved.model,
                voice=resolved.voice,
                instructions=resolved.instructions,
            )
        except Exception as exc:
            observe(fail={"code": "tts_failed", "message": str(exc)})
            log.error("❌ tts — %s", inbound_id, error=str(exc), exc_info=True)
            emit(
                writer,
                GRAPH_ERROR,
                {"inbound_id": inbound_id, "node": "tts", "error": str(exc)},
            )
            return {}

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        log.info(
            "✅ tts — %s · bytes=%d · model=%s",
            inbound_id,
            len(result.audio_bytes),
            result.model,
            elapsed_ms=elapsed_ms,
        )

        import base64

        audio_b64 = base64.b64encode(result.audio_bytes).decode()
        reply_id = state.get("reply_id") or ""
        duration_ms = result.duration_ms
        provider = str(getattr(result, "provider", "") or "")
        usage_metadata = getattr(result, "usage_metadata", None)
        if not isinstance(usage_metadata, dict):
            usage_metadata = {}
        metered = metered_text(provider, result.model, resolved.instructions, text)
        usage_counts = build_tts_usage(
            usage_metadata, duration_ms=duration_ms, text=metered
        )
        observe(
            usage={
                "provider": provider,
                "model": result.model,
                "input_tokens": usage_counts["input_tokens"],
                "tts_chars": len(text),
                "tts_text_tokens": usage_counts["tts_text_tokens"],
                "tts_audio_tokens": usage_counts["tts_audio_tokens"],
                "tts_audio_seconds": usage_counts["tts_audio_seconds"],
            },
            decision=("voiced", provider),
            output=(
                f"audio: {len(result.audio_bytes)} bytes · duration: {duration_ms}ms"
                f" · voice: {result.voice}"
            ),
        )
        payload = {
            "inbound_id": inbound_id,
            "chat_channel_id": state.get("chat_channel_id", 0),
            "reply_id": reply_id,
            "blob_id": "",
            "media_type": result.mime_type,
            "size": len(result.audio_bytes),
            "duration_ms": duration_ms,
            "audio_b64": audio_b64,
            "provider": provider,
            "model": result.model,
            "voice": result.voice,
            "input_characters": len(text),
            "input_text_tokens": usage_counts["input_tokens"],
            "generated_audio_seconds": usage_counts["tts_audio_seconds"],
            "usage_metadata": usage_metadata,
        }
        emit(writer, GRAPH_TTS_COMPLETED, payload)

        attachment: ReplyAudio = {
            "blob_id": "",
            "media_type": result.mime_type,
            "size": len(result.audio_bytes),
            "duration_ms": result.duration_ms,
            "media_path": "",
            "audio_b64": audio_b64,
        }
        return {"reply_audio": attachment}


    @graph_logged(captures={"decision"})
    async def finalize_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        """Emit the terminal graph-run lifecycle event.

        The aggregate agent status is about the whole graph run, not a node like
        ``memory_out``. A missing text reply is the first-pass fatal condition;
        everything after a text reply (for example TTS) is degradable.
        """
        inbound_id = state.get("inbound_id", "")
        chat_channel_id = int(state.get("chat_channel_id") or 0)
        reply_id = state.get("reply_id") or ""
        reply_text = state.get("reply_text") or ""
        observe(
            input=f"reply_id: {reply_id or '<empty>'} · reply: {reply_text}"
        )
        if reply_text and reply_id:
            observe(decision=("completed", "ok"), output="run: completed")
            emit(
            writer,
                GRAPH_RUN_COMPLETED,
                {
                    "inbound_id": inbound_id,
                    "chat_channel_id": chat_channel_id,
                    "reply_id": reply_id,
                },
            )
            return {}

        observe(
            fail={
                "code": "reply_generation_failed",
                "message": "reply generation failed",
                "decision": "failed",
            }
        )
        emit(
            writer,
            GRAPH_RUN_FAILED,
            {
                "inbound_id": inbound_id,
                "chat_channel_id": chat_channel_id,
                "code": "reply_generation_failed",
                "message": "I couldn't finish generating a reply.",
                "node": "finalize",
            },
        )
        return {}


    def _reply_knowledge_sources(self, state: GraphState) -> list[dict[str, Any]]:
        """Serialized knowledge sources to attach to the reply — only when chat citations are on."""
        if not self.prefs.cite_sources():
            return []
        return _serialize_knowledge_sources(state.get("knowledge_sources") or [])


    @graph_logged(captures={"decision"})
    async def compose_context_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        sources = state.get("knowledge_sources") or []
        # Instructions, Knowledge, and Memories are always present (sections render a
        # placeholder when empty); the citation instruction is conditional. Knowledge renders
        # from the structured sources (tagged, neutralized), not the pre-joined string.
        blocks = [
            block
            for block in (
                instructions_block(self.prefs.chat_instructions()),
                knowledge_block(sources),
                memory_block(state.get("retrieved_memories") or []),
                citation_block(
                    has_sources=bool(sources),
                    cite_enabled=self.prefs.cite_sources(),
                ),
            )
            if block is not None
        ]
        turn_context = self._assembler.assemble(blocks=blocks)
        source_names = ",".join(block.source for block in blocks) or "none"
        observe(
            input=(
                f"knowledge: {len(sources)} · "
                f"memories: {len(state.get('retrieved_memories') or [])}"
            ),
            decision=("composed", source_names),
            output=f"blocks: {source_names} · chars={len(turn_context)}",
        )
        return {"turn_context": turn_context}

    @graph_logged(captures={"usage", "decision"})
    async def call_model_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        messages: list[AnyMessage] = list(state.get("messages", []) or [])
        if not messages:
            observe(
                decision=("empty", "no_messages"),
                input="messages: 0",
                output="reply: <empty>",
            )
            return {}
        # Persona stays a stable system message (cache-friendly). The per-turn context block
        # (memory + knowledge + citation), assembled once by compose_context into
        # ``turn_context``, is injected ephemerally into the current user turn — context first,
        # question last — so it sits next to the query and never persists in ``messages``.
        # ``turn_context`` is absent for non-chat variants that skip compose_context.
        turn_context = (state.get("turn_context") or "").strip()
        inputs: list[AnyMessage] = list(messages)
        if turn_context:
            # The current user turn is the last HumanMessage (after a tool loop it is no longer
            # the final element). Enrich a copy of it; the stored message stays clean.
            for i in range(len(inputs) - 1, -1, -1):
                if isinstance(inputs[i], HumanMessage):
                    user_text = normalize_reply_content(inputs[i].content)
                    inputs[i] = HumanMessage(
                        content=f"{turn_context}\n\n## Last User Message\n{user_text}"
                    )
                    break
        if self._system_prompt:
            inputs = [SystemMessage(content=self._system_prompt), *inputs]
        # Preview the clean stored turn (not the enriched copy) + the tuning that ran. Model
        # is in the model column, so it's not repeated here.
        tuning = (
            f" · temp={self._temperature} max_tokens={self._max_tokens} thinking={self._thinking or 'off'}"
            if self._temperature is not None
            else ""
        )
        observe(input=f"text: {_last_human_message_preview(messages)}{tuning}")
        input_estimate = count_tokens_approximately(inputs)
        log.fineinfo(
            "call_model — input · count=%d tokens≈%d",
            len(inputs), input_estimate,
        )
        # Resolve identity up-front so a failed call still records WHICH model broke (the ledger
        # wrapper otherwise stamps only the exception class name, e.g. "googlegenerativeai").
        effective_model = self._model_id or str(state.get("model_id") or "")
        provider = effective_model.split(":", 1)[0] if ":" in effective_model else ""
        # Per-turn tools kill-switch: invoke the un-bound model when tools are disabled for this
        # turn (preference or per-chat opt-out) so no tool calls are emitted; should_continue then
        # routes to memory_out. ``bound`` already == model when no tools were compiled in.
        active = self._bound if state.get("tools_enabled", True) else self._model
        try:
            response = await active.ainvoke(inputs)
        except Exception as exc:
            # Record which model failed (the wrapper can't), then fail() adds decision + message;
            # re-raise so failure semantics are unchanged.
            observe(
                usage={"provider": provider, "model": effective_model},
                fail={"code": _error_slug(exc), "message": str(exc)},
            )
            raise
        usage_payload = llm_usage_payload(
            response,
            inbound_id=state.get("inbound_id", ""),
            chat_channel_id=int(state.get("chat_channel_id") or 0),
            model_id=self._model_id or str(state.get("model_id") or ""),
            estimated_input_tokens=input_estimate,
        )
        decision_kind, decision_detail = _llm_decision(response)
        reply_preview = normalize_reply_content(response.content)
        observe(
            usage={
                "provider": provider,
                "model": effective_model,
                "input_tokens": int(usage_payload.get("input_tokens") or input_estimate or 0),
                "output_tokens": int(usage_payload.get("output_tokens") or 0),
                "cached_input_tokens": int(usage_payload.get("cached_input_tokens") or 0),
                "reasoning_tokens": int(usage_payload.get("reasoning_tokens") or 0),
            },
            decision=(decision_kind, decision_detail),
            output=(
                f"reply: {reply_preview}"
                if reply_preview.strip()
                else _tool_calls_preview(getattr(response, "tool_calls", None) or [])
            ),
        )
        emit(
            writer,
            GRAPH_LLM_USAGE,
            usage_payload,
        )
        return {"messages": [response]}

    @graph_logged(captures={"decision"}, flush=False)
    async def tools_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        messages: list[AnyMessage] = list(state.get("messages", []) or [])
        if not messages:
            return {}
        last = messages[-1]
        if not isinstance(last, AIMessage) or not last.tool_calls:
            return {}

        out: list[ToolMessage] = []
        for idx, call in enumerate(last.tool_calls):
            tool_call_id = _tool_call_id(call)
            tool_name = _tool_call_name(call)
            args = _tool_call_args(call)
            tool = self._tools_by_name.get(tool_name)
            started = time.perf_counter()
            status = "completed"
            error: str | None = None
            try:
                if tool is None:
                    raise KeyError(f"unknown tool: {tool_name}")
                result = await tool.ainvoke(args)
                content = _tool_result_content(result)
            except Exception as exc:
                status = "failed"
                error = str(exc)
                content = f"Error: {error}"

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if status == "completed":
                record_child(
                    node=f"tools/{_error_slug(tool_name) or 'unknown'}",
                    status="ok",
                    elapsed_ms=elapsed_ms,
                    branch_index=idx,
                    input=_tool_input_preview(tool_name, args),
                    output=f"result: {content}",
                    decision=("ok", "ok"),
                )
            else:
                record_child(
                    node=f"tools/{_error_slug(tool_name) or 'unknown'}",
                    status="error",
                    elapsed_ms=elapsed_ms,
                    branch_index=idx,
                    input=_tool_input_preview(tool_name, args),
                    output=f"error: {error}",
                    fail={"code": _error_slug(error or "tool_error"), "decision": "client_error"},
                )
            emit(
                writer,
                GRAPH_TOOL_COMPLETED,
                {
                    "inbound_id": state.get("inbound_id", ""),
                    "chat_channel_id": int(state.get("chat_channel_id") or 0),
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "status": status,
                    "elapsed_ms": elapsed_ms,
                    "error": error,
                    "args": _tool_args_one_line(args),
                    "result": _tool_result_bounded(content)
                    if status == "completed"
                    else None,
                },
            )
            out.append(
                ToolMessage(
                    content=content,
                    tool_call_id=tool_call_id or tool_name,
                )
            )

        return {"messages": out}
