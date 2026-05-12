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
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from hiro_channel_sdk.log_scope_fields import (
    unified_message_log_scope,
)
from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.log import Logger, log_scope

from .agent_graph import ChatAgentGraph
from .agent_graph.base import BaseAgentGraph, _normalize_reply_content
from .comm_log import (
    LOG_IN,
    comm_extras,
    comm_kind,
    comm_peer_label,
    routing_requests_voice_reply,
)

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from ..services.tts import TTSService
    from .communication_manager import CommunicationManager
    from .server_context import ServerContext

log = Logger.get("AGENT")

# Keep the public helpers the old test surface imports.
__all__ = [
    "AgentManager",
    "_normalize_reply_content",
    "_audio_extension_for_media_type",
    "_reply_content_type",
]


def _reply_content_type(content: Any) -> str:
    if isinstance(content, list):
        return f"list[{len(content)}]"
    return type(content).__name__


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
    ) -> None:
        self._ctx = ctx
        self._comm = comm_manager
        self._tts = tts_service
        self._stt = None  # built in serve()
        self._vision = None
        self._credentials = None
        self._checkpointer = None
        self._graph: BaseAgentGraph | None = None
        # Compiled-graph cache keyed by (system_prompt_hash, model fingerprint).
        self._compiled_cache: OrderedDict[tuple[Any, ...], "CompiledStateGraph"] = OrderedDict()
        self._compiled_cache_max = 24

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
        from ..services.stt import create_stt_service
        from ..services.vision_service import VisionService

        wid = workspace_id_for_path(self._ctx.workspace_path)
        self._credentials = (
            CredentialStore(self._ctx.workspace_path, wid) if wid is not None else None
        )

        # Build the media services here (formerly in create_adapter_pipeline).
        log.info("🕒 Loading STT service")
        self._stt = create_stt_service(self._ctx.workspace_path)
        log.info("🕒 Loading Vision service")
        self._vision = VisionService(workspace_path=self._ctx.workspace_path)

        self._log_agent_config()

        db = str(db_path(self._ctx.workspace_path))
        async with AsyncSqliteSaver.from_conn_string(db) as checkpointer:
            self._checkpointer = checkpointer
            self._graph = ChatAgentGraph(
                workspace_path=self._ctx.workspace_path,
                stt_service=self._stt,
                vision_service=self._vision,
                tts_service=self._tts,
                credential_store=self._credentials,
                checkpointer=checkpointer,
            )
            log.info(
                "✅ AgentManager started — workspace · graph runner ready",
                db=db,
            )
            try:
                await self._ctx.stop_event.wait()
            finally:
                self._compiled_cache.clear()
                self._graph = None
                self._checkpointer = None

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
            load_preferences,
            resolve_character_llm,
            resolve_llm,
        )

        peer = comm_peer_label(msg, self._ctx)
        thread_id, channel_id, character_id = self._resolve_thread_character(msg)
        prefs = load_preferences(self._ctx.workspace_path)
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

        ch = self._load_character_for_channel(character_id)
        system_prompt = effective_character_system_prompt(ch)
        llm_entry = resolve_character_llm(
            ch.llm_models,
            prefs,
            self._ctx.workspace_path,
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
            "request_voice_reply": request_voice_reply,
            "voice_input_allowed": voice_input_allowed,
            "routing_metadata": dict(msg.routing.metadata or {}),
            "inbound_envelope": msg.model_dump(mode="json"),
            "transcripts": [],
            "visions": [],
            "errors": [],
            "messages": [],
        }
        config = {"configurable": {"thread_id": thread_id}}

        # Register per-run state slot for the subscriber. ``persisted_event``
        # is signaled by the subscriber once persist_inbound completes.
        self._comm.graph_subscriber.begin_run(msg.routing.id)
        if persisted_event is not None:
            self._comm.graph_subscriber.attach_persisted_event(
                msg.routing.id, persisted_event,
            )

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
                        await self._comm.graph_subscriber.dispatch(
                            msg, event_name, payload,
                        )
                # ``updates`` chunks are useful for fineinfo only; per-node
                # human-first lines are emitted by the nodes themselves.
        finally:
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
            "chat-graph-v1",
            fp,
        )

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
            credential_store=self._credentials,
        )
        # Tools are temporarily disabled; matches the prior agent_manager behavior.
        compiled = self._graph.build(
            model=model,
            tools=[],
            system_prompt=system_prompt,
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

    def _resolve_thread_character(self, msg: UnifiedMessage) -> tuple[str, int, str]:
        """Return ``(thread_id, channel_id, character_id)`` for this conversation."""
        from ..domain.character import default_character_id
        from ..domain.conversation_channel import resolve_chat_channel_from_metadata

        channel = resolve_chat_channel_from_metadata(
            self._ctx.workspace_path, msg.routing.metadata,
        )
        channel_id = int(channel.id)
        character_id = (channel.character_id or "").strip() or default_character_id(
            self._ctx.workspace_path,
        )
        return str(channel_id), channel_id, character_id

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
            from ..domain.preferences import load_preferences, resolve_llm

            prefs = load_preferences(self._ctx.workspace_path)
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


# Deliberate use to silence the unused-import lint while keeping a hook for
# future contextlib-based scoping in ``handle``.
_ = contextlib  # pragma: no cover
