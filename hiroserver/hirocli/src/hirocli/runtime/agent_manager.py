"""AgentManager — graph runner + event bridge.

Replaces the prior queue-draining worker. Now:

  - ``serve()`` opens the LangGraph checkpointer, builds the ``ChatAgentGraph``
    instance once per workspace, and waits on ``ctx.stop_event``.
  - ``handle(msg)`` is invoked per inbound message by ``InboundPipeline``.
    It resolves the chat channel + character, builds the initial graph state,
    streams the graph via ``astream(stream_mode=["updates", "custom"])``,
    and forwards every custom domain event to the
    ``GraphEventSubscriber`` owned by ``CommunicationManager``.

The graph (LangGraph) owns reasoning, tools, STT, vision and TTS as nodes.
Outbound side effects (persistence, mirror, transcript event, text reply,
voiced event, error fallback) live as graph-event subscribers on the comm
side — see ``graph_event_subscriber.py``.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from hiro_channel_sdk.log_scope_fields import (
    unified_message_log_scope,
)
from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.log import Logger, log_scope

from ..domain.events import DomainEvent, DomainEventType, get_domain_event_bus
from .agent_graph import (
    GRAPH_RUN_COMPLETED,
    GRAPH_RUN_FAILED,
    AgentServices,
    ChatAgentGraph,
    ChatGraphConfig,
)
from .agent_graph.ledger import RunAccumulator, current_run
from .agent_graph.tracing import langsmith_run_id
from .comm_log import (
    LOG_IN,
    comm_extras,
    comm_kind,
    comm_peer_label,
    routing_requests_voice_reply,
    routing_tools_enabled,
    routing_uses_knowledge,
)

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from ..domain.memory import MemoryService
    from ..services.tts import TTSService
    from ..tools.registry import ToolRegistry
    from .communication_manager import CommunicationManager
    from .server_context import ServerContext

log = Logger.get("AGENT")

# Idle memory-flush sweep cadence — how often the backstop runs (NOT how idle a conversation must
# be; that is the ``memory.extraction.idle_flush_hours`` pref). Internal on purpose: hourly is cheap
# (one indexed query for stale cursors) and keeps the ~12h idle threshold meaningfully timely.
_IDLE_SWEEP_INTERVAL_S = 3600.0

# Keep the public helpers the old test surface imports.
__all__ = [
    "AgentManager",
    "_audio_extension_for_media_type",
    "_reply_content_type",
]


def _reply_content_type(content: Any) -> str:
    if isinstance(content, list):
        return f"list[{len(content)}]"
    return type(content).__name__


def _message_input_preview(msg: UnifiedMessage) -> str:
    texts: list[str] = []
    for item in msg.content or []:
        content_type = str(getattr(item, "content_type", "") or "")
        if content_type == "text":
            texts.append(str(getattr(item, "body", "") or ""))
    return _preview(" ".join(texts))


def _update_text_preview(chunk: Any, field: str) -> str:
    if not isinstance(chunk, dict):
        return ""
    for value in chunk.values():
        if isinstance(value, dict) and value.get(field):
            return _preview(str(value.get(field) or ""))
    return ""


def _preview(value: str) -> str:
    return " ".join(str(value or "").split())[:280]


def _error_slug(exc: BaseException) -> str:
    name = exc.__class__.__name__.replace("Error", "").replace("Exception", "")
    return (
        "".join(ch for ch in name.lower() if ch.isalnum() or ch in {"_", "-", "."})[:80]
        or "error"
    )


def _audio_extension_for_media_type(media_type: str) -> str:
    """Re-export so tests that imported from agent_manager keep working."""
    from ..domain.media_store import audio_extension_for_media_type

    return audio_extension_for_media_type(media_type)


class AgentManager:
    """Owns the agent graph instance and dispatches per-message graph runs."""

    def __init__(
        self,
        ctx: "ServerContext",
        comm_manager: "CommunicationManager",
        tts_service: "TTSService | None" = None,
        *,
        tool_registry: "ToolRegistry | None" = None,
    ) -> None:
        self._ctx = ctx
        self._comm = comm_manager
        self._tts = tts_service
        self._tool_registry = tool_registry
        # Lazily built from full ToolRegistry via langchain_adapter on first compile.
        self._lc_agent_tools: list[Any] | None = None
        self._stt = None  # built in serve()
        self._vision = None
        self._memory: "MemoryService | None" = None
        self._credentials = None
        self._checkpointer = None
        self._graph: ChatAgentGraph | None = None
        # Compiled-graph cache keyed by (system_prompt_hash, model fingerprint).
        self._compiled_cache: OrderedDict[tuple[Any, ...], "CompiledStateGraph"] = OrderedDict()
        self._compiled_cache_max = 24
        # Serialize PROVIDERS_CHANGED handling — burst admin writes were racing
        # cache clears and service swaps.
        self._providers_change_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def serve(self) -> None:
        """Open the checkpointer + media services, build the graph, then wait.

        The async context for the SQLite checkpointer must stay open for the
        lifetime of the server, so ``serve`` keeps it open until
        ``ctx.stop_event`` fires. Per-message work is dispatched from
        ``InboundPipeline`` via :meth:`handle`.
        """
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        from ..domain.credential_store import CredentialStore
        from ..domain.db import db_path
        from ..domain.workspace import workspace_id_for_path
        from ..services.memory import create_memory_service
        from ..services.stt import create_stt_service
        from ..services.vision_service import VisionService

        wid = workspace_id_for_path(self._ctx.workspace_path)
        self._credentials = (
            CredentialStore(self._ctx.workspace_path, wid) if wid is not None else None
        )

        # Build the media services here (formerly in create_adapter_pipeline).
        log.info("🕒 Loading STT service")
        self._stt = create_stt_service(
            self._ctx.workspace_path,
            prefs=self._current_preferences(),
        )
        log.info("🕒 Loading Vision service")
        self._vision = VisionService(workspace_path=self._ctx.workspace_path)
        log.info("Loading Memory service")
        self._memory = create_memory_service(
            self._ctx.workspace_path,
            prefs=self._current_preferences(),
            credential_store=self._credentials,
        )
        self._ctx.memory_service = self._memory

        self._log_agent_config()

        db = str(db_path(self._ctx.workspace_path))
        async with AsyncSqliteSaver.from_conn_string(db) as checkpointer:
            self._checkpointer = checkpointer
            from ..services.memory.models import MemoryRetrievalModelCache
            from .agent_graph.ledger import LedgerSink

            services = AgentServices(
                workspace_path=self._ctx.workspace_path,
                ledger_sink=LedgerSink(self._ctx.workspace_path),
                stt=self._stt,
                vision=self._vision,
                tts=self._tts,
                memory=self._memory,
                credentials=self._credentials,
                checkpointer=checkpointer,
                preferences=self._ctx.preferences,
                knowledge_subgraph=self._build_knowledge_subgraph(),
                # C2: cache the recall model across turns (rebuilt only when its spec changes).
                memory_retrieval_models=MemoryRetrievalModelCache(),
            )
            self._graph = ChatAgentGraph(services)
            # Hot-reload STT/TTS when workspace model defaults change. Nodes read
            # ``self._stt`` / ``self._tts`` per call, so swapping attributes is enough
            # (compiled graphs are for chat LLM only).
            self._ctx.preference_reactor.on_change(
                "llm.default_stt",
                self._reload_stt_on_change,
                key="agent.stt",
            )
            self._ctx.preference_reactor.on_change(
                "llm.default_tts",
                self._reload_tts_on_change,
                key="agent.tts",
            )
            self._ctx.preference_reactor.on_change(
                "memory",
                self._reload_memory_on_change,
                key="agent.memory",
            )
            self._ctx.preference_reactor.on_change(
                "llm.default_tuning_profile",
                self._evict_compiled_cache_on_llm_tuning_change,
                key="agent.chat-cache",
            )
            self._ctx.preference_reactor.on_change(
                "tuning_profiles",
                self._reload_tuning_profiles_on_change,
                key="agent.tuning-profiles",
            )
            # Knowledge retrieval (hybrid/rewrite-model/top_k…) is read by the subgraph nodes;
            # rebuild the compiled subgraph and drop chat graphs so the new shape/settings apply.
            self._ctx.preference_reactor.on_change(
                "knowledge",
                self._reload_knowledge_on_change,
                key="agent.knowledge",
            )
            # The Graphiti graph engine (top-level ``graph.*``) is SHARED by knowledge
            # retrieval and agent memory (mem0 → Graphiti). It used to live under
            # ``knowledge.graph`` (caught by the knowledge reactor above); now that it's a
            # top-level section, rebuild BOTH consumers when it changes, or an engine edit
            # (extraction model / embedder / search recipe…) would silently not take effect.
            self._ctx.preference_reactor.on_change(
                "graph",
                self._reload_knowledge_on_change,
                key="agent.graph-knowledge",
            )
            self._ctx.preference_reactor.on_change(
                "graph",
                self._reload_memory_on_change,
                key="agent.graph-memory",
            )
            # Providers/admin mutations write ``providers.json`` via another
            # ``CredentialStore`` instance — keep graph caches and media services in sync.
            bus = get_domain_event_bus()
            bus.subscribe(DomainEventType.PROVIDERS_CHANGED, self._handle_providers_changed)
            log.info(
                "✅ AgentManager started — workspace · graph runner ready",
                db=db,
            )
            # Backstop for windowed memory ingestion: an hourly sweep flushes conversations idle
            # beyond memory.extraction.idle_flush_hours (a user who never returns to trigger a normal
            # flush). Lives for the server's lifetime alongside the stop-event wait.
            sweep_task = asyncio.create_task(self._idle_sweep_loop())
            try:
                await self._ctx.stop_event.wait()
            finally:
                sweep_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await sweep_task
                bus.unsubscribe(DomainEventType.PROVIDERS_CHANGED, self._handle_providers_changed)
                self._compiled_cache.clear()
                self._graph = None
                self._checkpointer = None
                await _close_memory_service(self._memory)
                self._memory = None
                self._ctx.memory_service = None

    async def _idle_sweep_loop(self) -> None:
        """Hourly idle-flush backstop for windowed memory ingestion. Each tick, flush pending turns
        for conversations idle beyond ``memory.extraction.idle_flush_hours``. No-op while memory or
        extraction is off. Sleeps on the stop-event so shutdown is immediate (never a full hour)."""
        from ..services.memory.windowed_ingest import sweep_idle_conversations

        while not self._ctx.stop_event.is_set():
            try:
                # Sleep up to one interval, but wake instantly on shutdown.
                await asyncio.wait_for(
                    self._ctx.stop_event.wait(), timeout=_IDLE_SWEEP_INTERVAL_S
                )
                return  # stop_event fired → exit the loop
            except asyncio.TimeoutError:
                pass  # interval elapsed → run a sweep

            memory = self._memory
            prefs = self._current_preferences()
            mem_prefs = getattr(prefs, "memory", None)
            ext = getattr(mem_prefs, "extraction", None)
            if (
                memory is None
                or not getattr(mem_prefs, "enabled", False)
                or not getattr(ext, "enabled", True)
            ):
                continue
            try:
                await sweep_idle_conversations(
                    memory,
                    workspace_path=self._ctx.workspace_path,
                    idle_flush_hours=int(getattr(ext, "idle_flush_hours", 12)),
                    window_turns=int(getattr(ext, "window_turns", 4)),
                    session_gap_minutes=int(getattr(ext, "session_gap_minutes", 120)),
                    chunk_min_tokens=int(getattr(ext, "chunk_min_tokens", 1000)),
                    user_name=(getattr(mem_prefs, "user_name", "") or "").strip(),
                )
            except Exception:
                log.warning("⚠️ memory idle sweep — tick failed (skipped)", exc_info=True)

    # ------------------------------------------------------------------
    # Per-message entry point
    # ------------------------------------------------------------------

    async def handle(
        self,
        msg: UnifiedMessage,
        *,
        persisted_event: asyncio.Event | None = None,
    ) -> None:
        """Run the graph for a single inbound message.

        ``persisted_event`` is set as soon as the inbound persistence
        subscriber finishes (used by synthetic injectors that need the row
        visible in the DB before returning — e.g. the ``message_send`` tool).
        """
        if self._graph is None:
            log.warning(
                "⚠️ Graph not ready — message dropped",
                msg_id=msg.routing.id,
            )
            if persisted_event is not None:
                persisted_event.set()
            return

        # Re-open log scope: this runs in a task spawned by InboundPipeline.
        (
            _dev, _mid, _meth, _pv, _tc, _tsc,
        ) = unified_message_log_scope(msg, direction="inbound")
        with log_scope(
            device_id=_dev, msg_id=_mid, method=_meth,
            text_preview=_pv, traffic_class=_tc, traffic_subclass=_tsc,
        ):
            try:
                await self._handle_inner(msg, persisted_event=persisted_event)
            except Exception as exc:
                log.error(
                    f"❌ graph run failed — {comm_peer_label(msg, self._ctx)} · {comm_kind(msg)}",
                    error=str(exc),
                    **comm_extras(msg),
                    exc_info=True,
                )
                if persisted_event is not None and not persisted_event.is_set():
                    # Unblock callers that were waiting on persistence.
                    persisted_event.set()

    async def _handle_inner(
        self,
        msg: UnifiedMessage,
        *,
        persisted_event: asyncio.Event | None,
    ) -> None:
        from ..domain.character import effective_character_system_prompt
        from ..domain.preferences import (
            resolve_character_llm,
            resolve_llm,
        )

        peer = comm_peer_label(msg, self._ctx)
        thread_id, channel_id, character_id, data_user_id = self._resolve_thread_character(msg)
        prefs = self._current_preferences()
        voice_input_allowed = bool(
            prefs.media.input.voice
            and resolve_llm(
                prefs,
                self._ctx.workspace_path,
                "stt",
                credential_store=self._credentials,
            )
            is not None
        )
        request_voice_reply = routing_requests_voice_reply(msg.routing.metadata)
        # Per-message knowledge toggle (default on); the fan-out edge skips retrieval when off.
        knowledge_enabled = routing_uses_knowledge(msg.routing.metadata)
        # Tools kill-switch: global preference AND the per-chat opt-out. Either off => no tools bound
        # this turn. call_model invokes the un-bound model when disabled, so should_continue routes
        # straight to memory_out (no tools node hop).
        tools_enabled = bool(prefs.chat.tools_enabled) and routing_tools_enabled(
            msg.routing.metadata
        )

        ch = self._load_character_for_channel(character_id)
        system_prompt = effective_character_system_prompt(ch)
        llm_entry = resolve_character_llm(
            ch.llm_models,
            prefs,
            self._ctx.workspace_path,
            tuning_profile=getattr(ch, "tuning_profile", None),
            credential_store=self._credentials,
        )
        if llm_entry is None:
            await self._send_no_llm_reply(msg)
            if persisted_event is not None:
                persisted_event.set()
            return

        try:
            compiled = self._get_or_compile(llm_entry, system_prompt)
        except Exception as exc:
            log.error(
                f"❌ Agent build failed — {peer} · {comm_kind(msg)}",
                error=str(exc),
                **comm_extras(msg, character_id=character_id, model_id=llm_entry.model_id),
                exc_info=True,
            )
            await self._send_build_failed_reply(msg)
            if persisted_event is not None:
                persisted_event.set()
            return

        log.info(
            f"{LOG_IN} graph run — {peer} · {comm_kind(msg)} · voice_reply={'yes' if request_voice_reply else 'no'}",
            **comm_extras(
                msg,
                thread_id=thread_id,
                character_id=character_id,
                model_id=llm_entry.model_id,
            ),
        )

        # Initial state. ``inbound_envelope`` carries bytes (audio body) into
        # the ingest node; ingest splits them out into per-modality fan-out
        # inputs and gather clears them so they never persist in checkpoint.
        initial_state = {
            "inbound_id": msg.routing.id,
            "chat_channel_id": channel_id,
            "thread_id": thread_id,
            "character_id": character_id,
            "data_user_id": data_user_id,
            "model_id": llm_entry.model_id,
            "request_voice_reply": request_voice_reply,
            "voice_input_allowed": voice_input_allowed,
            "knowledge_enabled": knowledge_enabled,
            "tools_enabled": tools_enabled,
            "routing_metadata": dict(msg.routing.metadata or {}),
            "inbound_envelope": msg.model_dump(mode="json"),
            "transcripts": [],
            "visions": [],
            "errors": [],
            "messages": [],
        }
        ledger_run_id = f"chat-{msg.routing.id}"
        config = {
            "run_id": langsmith_run_id(ledger_run_id),
            "run_name": "chat",
            "tags": [
                f"character:{character_id}",
                f"chat_channel_id:{channel_id}",
                f"voice_input:{bool(voice_input_allowed)}",
            ],
            "metadata": {"ledger_run_id": ledger_run_id},
            "configurable": {"thread_id": thread_id, "run_id": ledger_run_id},
        }

        # Register per-run state slot for the subscriber. ``persisted_event``
        # is signaled by the subscriber once persist_inbound completes.
        self._comm.graph_subscriber.begin_run(msg.routing.id)
        if persisted_event is not None:
            self._comm.graph_subscriber.attach_persisted_event(
                msg.routing.id, persisted_event,
            )

        routing_metadata = dict(msg.routing.metadata or {})
        input_preview = _message_input_preview(msg)
        output_preview = ""
        terminal_status = "completed"
        terminal_decision = "completed"
        terminal_detail = "text_reply"
        terminal_error = ""
        # The per-turn ledger sink lives on the graph's AgentServices — ``ChatAgentGraph`` exposes no
        # ``_ledger_sink`` attribute, so the old ``getattr(self._graph, "_ledger_sink", None)`` always
        # resolved to None: no RunAccumulator was opened, so chat turns wrote NO ``@run`` aggregate
        # row (→ they vanished from the Graph Runs list) and ``current_run`` was never set (→ a memory
        # ingest couldn't nest under the turn). Read it from services, the same sink the nodes use.
        ledger_sink = getattr(getattr(self._graph, "services", None), "ledger_sink", None)
        accumulator = (
            RunAccumulator(
                sink=ledger_sink,
                run_id=ledger_run_id,
                inbound_id=msg.routing.id,
                chat_channel_id=channel_id,
                device_id=str(
                    getattr(msg.routing, "sender_id", "")
                    or routing_metadata.get("device_id")
                    or ""
                ),
                user_id=str(routing_metadata.get("user_id") or ""),
                character_id=character_id,
            )
            if ledger_sink is not None
            else None
        )
        run_token = current_run.set(accumulator) if accumulator is not None else None
        t0 = time.perf_counter()
        try:
            async for stream_mode, chunk in compiled.astream(
                initial_state,
                config=config,
                stream_mode=["updates", "custom"],
            ):
                if stream_mode == "custom":
                    event_name = chunk.get("event")
                    payload = chunk.get("payload") or {}
                    if isinstance(event_name, str):
                        if event_name == GRAPH_RUN_COMPLETED:
                            terminal_status = "completed"
                            terminal_decision = "completed"
                            terminal_detail = "text_reply"
                            terminal_error = ""
                        elif event_name == GRAPH_RUN_FAILED:
                            terminal_status = "failed"
                            terminal_decision = "failed"
                            terminal_detail = str(
                                payload.get("code") or "reply_generation_failed"
                            )
                            terminal_error = terminal_detail
                        await self._comm.graph_subscriber.dispatch(
                            msg, event_name, payload,
                        )
                elif stream_mode == "updates":
                    input_preview = input_preview or _update_text_preview(chunk, "user_text")
                    output_preview = output_preview or _update_text_preview(chunk, "reply_text")
                # ``updates`` chunks are useful for fineinfo only; per-node
                # human-first lines are emitted by the nodes themselves.
        except asyncio.CancelledError:
            terminal_status = "cancelled"
            terminal_decision = "cancelled"
            terminal_detail = "cancelled"
            terminal_error = "cancelled"
            raise
        except Exception as exc:
            terminal_status = "failed"
            terminal_decision = "failed"
            terminal_detail = "reply_generation_failed"
            terminal_error = _error_slug(exc)
            log.error(
                "❌ graph failed — %s · %s",
                peer, comm_kind(msg),
                error=str(exc), exc_info=True,
            )
            await self._comm.graph_subscriber.dispatch(
                msg,
                GRAPH_RUN_FAILED,
                {
                    "inbound_id": msg.routing.id,
                    "chat_channel_id": channel_id,
                    "code": "reply_generation_failed",
                    "message": "I couldn't finish generating a reply.",
                },
            )
        finally:
            if accumulator is not None:
                accumulator.sink.write_run_row(
                    accumulator,
                    status=terminal_status,
                    error_code=terminal_error,
                    decision_kind=terminal_decision,
                    decision_detail=terminal_detail,
                    input_preview=input_preview,
                    output_preview=output_preview,
                )
                accumulator.sink.evict_run(ledger_run_id)
            if run_token is not None:
                current_run.reset(run_token)
            self._comm.graph_subscriber.end_run(msg.routing.id)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            log.fineinfo(
                f"graph done — {peer} · {comm_kind(msg)} · {elapsed_ms}ms",
                **comm_extras(msg, thread_id=thread_id, elapsed_ms=elapsed_ms),
            )
            if persisted_event is not None and not persisted_event.is_set():
                # Defensive: never leave a synchronous caller blocked.
                persisted_event.set()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compile_key(self, llm_entry, system_prompt: str) -> tuple[Any, ...]:
        fp = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
        return (
            llm_entry.model_id,
            round(float(llm_entry.temperature), 6),
            int(llm_entry.max_tokens),
            getattr(llm_entry, "thinking", None),
            "chat-graph-v1",
            fp,
        )

    def _langchain_tools_for_agent(self) -> list[Any]:
        """Agent-surfaced, default-enabled Hiro tools as LangChain StructuredTools."""
        reg = self._tool_registry
        if reg is None:
            return []
        from ..tools.langchain_adapter import to_langchain_list

        tools = reg.agent_tools()
        log.info(
            "✅ Agent tools bound — HiroServer",
            count=len(tools),
            total=len(reg.tool_instances()),
            names=[t.name for t in tools],
        )
        return to_langchain_list(tools)

    def _get_or_compile(self, llm_entry, system_prompt: str):
        from ..domain.model_factory import create_chat_model

        key = self._compile_key(llm_entry, system_prompt)
        compiled = self._compiled_cache.get(key)
        if compiled is not None:
            self._compiled_cache.move_to_end(key)
            return compiled

        assert self._graph is not None
        log.fineinfo(
            "Building agent — chat · %s",
            llm_entry.model_id,
            temperature=llm_entry.temperature,
            max_tokens=llm_entry.max_tokens,
        )
        model = create_chat_model(
            llm_entry.model_id,
            workspace_path=self._ctx.workspace_path,
            temperature=llm_entry.temperature,
            max_tokens=llm_entry.max_tokens,
            thinking=getattr(llm_entry, "thinking", None),
            num_ctx=getattr(llm_entry, "num_ctx", None),
            credential_store=self._credentials,
        )
        # Tools are bound into the compiled graph once and memoized; per-turn enable/disable is a
        # runtime decision (state["tools_enabled"]) handled in call_model, not a recompile.
        if self._lc_agent_tools is None:
            self._lc_agent_tools = self._langchain_tools_for_agent()
        compiled = self._graph.build(
            ChatGraphConfig(
                model=model,
                tools=self._lc_agent_tools,
                model_id=llm_entry.model_id,
                system_prompt=system_prompt,
                temperature=llm_entry.temperature,
                max_tokens=llm_entry.max_tokens,
                thinking=getattr(llm_entry, "thinking", None),
            )
        )
        self._compiled_cache[key] = compiled
        self._compiled_cache.move_to_end(key)
        while len(self._compiled_cache) > self._compiled_cache_max:
            self._compiled_cache.popitem(last=False)
        return compiled

    def _load_character_for_channel(self, character_id: str):
        from ..domain.character import default_character_id, load_character_from_disk

        wp = self._ctx.workspace_path
        cid = (character_id or "").strip() or default_character_id(wp)
        try:
            return load_character_from_disk(wp, cid)
        except FileNotFoundError:
            fallback = default_character_id(wp)
            log.warning(
                "⚠️ Character folder missing — using default character",
                requested=cid, fallback=fallback,
            )
            return load_character_from_disk(wp, fallback)

    def _resolve_thread_character(self, msg: UnifiedMessage) -> tuple[str, int, str, int]:
        """Return ``(thread_id, channel_id, character_id, data_user_id)`` for this conversation."""
        from ..domain.character import default_character_id
        from ..domain.conversation_channel import resolve_chat_channel_from_metadata

        channel = resolve_chat_channel_from_metadata(
            self._ctx.workspace_path, msg.routing.metadata,
        )
        channel_id = int(channel.id)
        character_id = (channel.character_id or "").strip() or default_character_id(
            self._ctx.workspace_path,
        )
        return str(channel_id), channel_id, character_id, int(channel.user_id)

    async def _send_no_llm_reply(self, msg: UnifiedMessage) -> None:
        from .graph_event_subscriber import _build_reply_envelope

        reply = _build_reply_envelope(
            msg,
            "The agent is not available — no chat LLM is configured. "
            "Please register an LLM in preferences.json.",
            reply_id="",
        )
        await self._comm.enqueue_outbound(reply)
        log.info(
            "⬆️ Fallback reply enqueued — %s · no_chat_llm",
            comm_peer_label(msg, self._ctx),
        )

    async def _send_build_failed_reply(self, msg: UnifiedMessage) -> None:
        from .graph_event_subscriber import _build_reply_envelope

        reply = _build_reply_envelope(
            msg,
            "The assistant could not load its model for this conversation. "
            "Check workspace LLM configuration and try again.",
            reply_id="",
        )
        await self._comm.enqueue_outbound(reply)

    def _log_agent_config(self) -> None:
        try:
            from ..domain.preferences import resolve_llm

            prefs = self._current_preferences()
            llm = resolve_llm(
                prefs, self._ctx.workspace_path, "chat",
                credential_store=self._credentials,
            )
            if llm:
                log.info(
                    "✅ Workspace chat default — %s (characters may override)",
                    llm.model_id,
                    temperature=llm.temperature, max_tokens=llm.max_tokens,
                )
            else:
                log.error(
                    "❌ No chat LLM configured — replies will be canned fallbacks",
                )
        except Exception as exc:
            log.error("❌ Failed to load agent config", error=str(exc), exc_info=True)

    def _current_preferences(self):
        prefs_runtime = getattr(self._ctx, "preferences", None)
        if prefs_runtime is not None:
            return prefs_runtime.current
        from ..domain.preferences import load_preferences

        return load_preferences(self._ctx.workspace_path)

    async def _handle_providers_changed(self, event: DomainEvent) -> None:
        """Refresh credential metadata from disk, drop compiled graphs, rebuild STT/TTS/Vision.

        ``CredentialStore`` publishes ``PROVIDERS_CHANGED`` after every ``providers.json``
        write so admin/CLI mutations propagate without restarting HiroServer.
        """
        if event.workspace_path != self._ctx.workspace_path:
            return
        async with self._providers_change_lock:
            reason = event.payload.get("reason", "")
            log.info(
                "🔌 Providers updated — HiroServer · reloading agent bindings · providers.changed",
                reason=reason,
            )
            if self._credentials is not None:
                self._credentials.sync_providers_document_from_disk()
            self._compiled_cache.clear()
            if self._vision is not None:
                self._vision.invalidate_workspace_credentials()

            stt_ok = await self._attach_new_stt_service(context="providers change")
            tts_ok = await self._attach_new_tts_service(context="providers change")
            memory_ok = await self._attach_new_memory_service(context="providers change")
            if stt_ok and tts_ok and memory_ok:
                log.info(
                    "Providers change applied - services rebound; vision cache cleared",
                    stt_ok=stt_ok,
                    tts_ok=tts_ok,
                    memory_ok=memory_ok,
                )
            elif stt_ok or tts_ok or memory_ok:
                log.warning(
                    "Providers change partially applied - services rebound",
                    stt_ok=stt_ok,
                    tts_ok=tts_ok,
                    memory_ok=memory_ok,
                )
            else:
                log.warning(
                    "Providers change - service rebound failed",
                    stt_ok=stt_ok,
                    tts_ok=tts_ok,
                    memory_ok=memory_ok,
                )

    async def _attach_new_stt_service(self, *, context: str) -> bool:
        """Build ``STTService`` from current prefs + credentials; swap onto graph."""
        from ..services.stt import create_stt_service

        try:
            new_stt = await asyncio.to_thread(
                create_stt_service,
                self._ctx.workspace_path,
                prefs=self._current_preferences(),
            )
        except Exception as exc:
            log.error(
                f"❌ STT rebuild failed — HiroServer · {context} · keeping previous instance",
                error=str(exc),
                exc_info=True,
            )
            return False

        self._stt = new_stt
        if self._graph is not None:
            self._graph.services.stt = new_stt
        log.fineinfo(
            "STT rebound — HiroServer",
            context=context,
            available=new_stt.is_available() if new_stt is not None else False,
        )
        return True

    async def _attach_new_tts_service(self, *, context: str) -> bool:
        """Build ``TTSService`` from current prefs + credentials; swap onto graph."""
        from ..services.tts import create_tts_service

        try:
            new_tts = await asyncio.to_thread(
                create_tts_service,
                self._ctx.workspace_path,
                prefs=self._current_preferences(),
            )
        except Exception as exc:
            log.error(
                f"❌ TTS rebuild failed — HiroServer · {context} · keeping previous instance",
                error=str(exc),
                exc_info=True,
            )
            return False

        self._tts = new_tts
        if self._graph is not None:
            self._graph.services.tts = new_tts
        log.fineinfo(
            "TTS rebound — HiroServer",
            context=context,
            available=new_tts.is_available() if new_tts is not None else False,
        )
        return True

    async def _attach_new_memory_service(self, *, context: str) -> bool:
        """Build long-term memory service from current prefs + credentials; swap onto graph."""
        from ..services.memory import create_memory_service

        old_memory = self._memory
        self._memory = None
        self._ctx.memory_service = None
        if self._graph is not None:
            self._graph.services.memory = None
        await _close_memory_service(old_memory)

        try:
            new_memory = await asyncio.to_thread(
                create_memory_service,
                self._ctx.workspace_path,
                self._current_preferences(),
                credential_store=self._credentials,
            )
        except Exception as exc:
            log.error(
                f"Memory rebuild failed - HiroServer - {context}",
                error=str(exc),
                exc_info=True,
            )
            return False

        self._memory = new_memory
        self._ctx.memory_service = new_memory
        if self._graph is not None:
            self._graph.services.memory = new_memory
            # C2: drop the cached recall model too — a credential/provider change can leave the
            # model_id unchanged (so the spec key wouldn't self-invalidate) while its client holds
            # stale credentials. This choke point fires on both memory-pref and providers changes.
            cache = self._graph.services.memory_retrieval_models
            if cache is not None:
                cache.clear()
        log.fineinfo(
            "Memory rebound - HiroServer",
            context=context,
            available=new_memory is not None,
        )
        return True

    async def _reload_stt_on_change(
        self,
        workspace_path,
        changes: dict[str, tuple[Any, Any]],
    ) -> None:
        """Rebuild ``STTService`` after ``llm.default_stt`` changes.

        Called by ``PreferenceReactor`` when an effective change to
        ``llm.default_stt`` is observed for this workspace. Builds a fresh
        ``STTService`` and swaps it onto both the manager and the live graph
        so the next message uses the new model.
        """
        old_value, new_value = changes.get("llm.default_stt", (None, None))
        ok = await self._attach_new_stt_service(context="preferences.default_stt")
        if ok:
            log.info(
                "✅ STT reloaded — preferences",
                old=old_value,
                new=new_value,
                available=self._stt.is_available() if self._stt is not None else False,
            )

    async def _reload_tts_on_change(
        self,
        workspace_path,
        changes: dict[str, tuple[Any, Any]],
    ) -> None:
        """Rebuild ``TTSService`` after ``llm.default_tts`` changes."""
        old_value, new_value = changes.get("llm.default_tts", (None, None))
        ok = await self._attach_new_tts_service(context="preferences.default_tts")
        if ok:
            log.info(
                "✅ TTS reloaded — preferences",
                old=old_value,
                new=new_value,
                available=self._tts.is_available() if self._tts is not None else False,
            )

    async def _reload_memory_on_change(
        self,
        workspace_path,
        changes: dict[str, tuple[Any, Any]],
    ) -> None:
        """Rebuild long-term memory after memory-related preferences change."""
        # Memory rides the shared Graphiti engine (mem0 → Graphiti, Phase 5): rebuild on its
        # feature toggle + recall knobs AND on any graph-engine pref change (models / embedder /
        # search). ``memory.extraction.*`` is read at runtime, so it needs no rebuild.
        relevant_paths = {"memory.enabled"}
        relevant_prefixes = ("memory.search.", "graph.")
        if not any(path in relevant_paths for path in changes) and not any(
            path.startswith(relevant_prefixes) for path in changes
        ):
            return
        ok = await self._attach_new_memory_service(context="preferences.memory")
        if ok:
            log.info(
                "Memory reloaded - preferences",
                paths=sorted(changes.keys()),
                available=self._memory is not None,
            )

    async def _evict_compiled_cache_on_llm_tuning_change(
        self,
        workspace_path,
        changes: dict[str, tuple[Any, Any]],
    ) -> None:
        """Drop compiled agent graphs after model tuning changes."""
        self._compiled_cache.clear()
        log.info(
            "Chat graph cache evicted - preferences",
            paths=sorted(changes.keys()),
        )

    async def _reload_tuning_profiles_on_change(
        self,
        workspace_path,
        changes: dict[str, tuple[Any, Any]],
    ) -> None:
        """Apply tuning profile edits to chat cache and memory service."""
        self._compiled_cache.clear()
        ok = await self._attach_new_memory_service(context="preferences.tuning_profiles")
        log.info(
            "Tuning profiles reloaded - preferences",
            paths=sorted(changes.keys()),
            memory_available=self._memory is not None,
            memory_reloaded=ok,
        )

    def _build_knowledge_subgraph(self):
        """Compile the retrieval-only knowledge subgraph from the workspace knowledge service.

        Returns ``None`` when knowledge is unavailable; the chat graph then omits the knowledge
        branch entirely. The subgraph is invoked per chat turn and inherits the chat run's ledger,
        so its ``knowledge/*`` node costs fold into that turn (no separate run).
        """
        # Runtime gate: when the ``knowledge`` feature is disabled, don't wire the
        # retrieval subgraph at all. Returning None makes the chat graph omit the
        # knowledge branch (see nodes/knowledge.py is_active), so there is no per-turn
        # rewrite LLM call and no empty knowledge context block. Mirrors the `devices`
        # runtime gate — the feature flag now controls runtime, not just UI/CLI/API.
        from ..domain.features import feature_active

        if not feature_active("knowledge"):
            return None
        manager = getattr(self._ctx, "knowledge_manager", None)
        service = getattr(manager, "service", None) if manager is not None else None
        if service is None:
            return None
        from ..domain.workspace import workspace_id_for_path
        from ..services.knowledge.agent import KnowledgeAgentGraph, KnowledgeGraphConfig
        from .agent_graph.ledger import LedgerSink
        from .agent_graph.services import AgentServices

        try:
            # Subgraph carries its own minimal ``AgentServices`` — invoked inside the chat
            # run, its ``knowledge/*`` ledger rows still inherit the active run_id via the
            # LangGraph state, so cost folds into the chat turn (no separate ledger run).
            sub_services = AgentServices(
                workspace_path=self._ctx.workspace_path,
                ledger_sink=LedgerSink(self._ctx.workspace_path),
            )
            builder = KnowledgeAgentGraph(sub_services)
            return builder.build_retrieval(
                KnowledgeGraphConfig(
                    service=service,
                    prefs=self._current_preferences(),
                    workspace_id=workspace_id_for_path(self._ctx.workspace_path),
                )
            )
        except Exception as exc:
            log.warning(
                "⚠️ knowledge subgraph build failed — chat knowledge disabled",
                error=str(exc),
                exc_info=True,
            )
            return None

    async def _reload_knowledge_on_change(
        self,
        workspace_path,
        changes: dict[str, tuple[Any, Any]],
    ) -> None:
        """Rebuild the knowledge subgraph and drop chat graphs after knowledge prefs change."""
        if self._graph is None:
            return
        self._graph.services.knowledge_subgraph = self._build_knowledge_subgraph()
        self._compiled_cache.clear()
        log.info(
            "✅ knowledge subgraph rebuilt — chat graph cache cleared",
            paths=sorted(changes.keys()),
        )


# Deliberate use to silence the unused-import lint while keeping a hook for
# future contextlib-based scoping in ``handle``.
_ = contextlib  # pragma: no cover


async def _close_memory_service(service: "MemoryService | None") -> None:
    close = getattr(service, "close", None)
    if not callable(close):
        return
    result = close()
    if inspect.isawaitable(result):
        await result
