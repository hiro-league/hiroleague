"""BaseAgentGraph — reusable nodes for chat agent graphs.

Nodes are bound methods on this class. Concrete graphs (``ChatAgentGraph``)
inherit this base, override ``build()`` to wire nodes into a ``StateGraph``,
and choose which features (TTS, parallel media branches, tools) participate.

Why a class instead of free functions:
  - Services (STT, TTS, vision, model factory, credential store, checkpointer)
    are injected once at construction. Nodes read them through ``self`` and
    stay parameter-free at the graph layer (LangGraph passes ``state`` and
    optionally ``writer`` / ``config``).
  - The same node implementations are shared across future graph variants
    without copy-paste.

Bytes never enter the parent (checkpointed) state. STT/vision sub-states
ride on ``langgraph.types.Send`` payloads; the resulting transcripts /
descriptions are merged back through reducers.
"""

from __future__ import annotations

import json
import math
import time
import uuid
from typing import TYPE_CHECKING, Any

from hiro_channel_sdk.constants import (
    CONTENT_TYPE_AUDIO,
    CONTENT_TYPE_IMAGE,
    CONTENT_TYPE_TEXT,
)
from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.llm_usage import (
    gemini_usage_aggregate_fallback,
    modality_token_count,
)
from hiro_commons.log import Logger
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer, Send, StreamWriter

from ...domain.memory import resolve_memory_user_id
from ...domain.preferences import DEFAULT_MAX_HISTORY_MESSAGES
from .context_assembly import (
    ContextAssembler,
    citation_block,
    instructions_block,
    knowledge_block,
    memory_block,
)
from .events import (
    GRAPH_ERROR,
    GRAPH_INGEST_COMPLETED,
    GRAPH_LLM_USAGE,
    GRAPH_MEMORY_RETRIEVED,
    GRAPH_MEMORY_STORED,
    GRAPH_REPLY_COMPLETED,
    GRAPH_RUN_COMPLETED,
    GRAPH_RUN_FAILED,
    GRAPH_STT_COMPLETED,
    GRAPH_TOOL_COMPLETED,
    GRAPH_TTS_COMPLETED,
    GRAPH_VISION_COMPLETED,
    make_event,
)
from .ledger import (
    LedgerSink,
    current_entry,
    current_substep,
    graph_logged,
    wrap_graph_callable,
    wrap_graph_node,
)
from .state import (
    AudioItem,
    GraphState,
    ImageItem,
    NodeError,
    ReplyAudio,
    Transcript,
    Vision,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ...domain.credential_store import CredentialStore
    from ...domain.memory import MemoryService
    from ...runtime.preferences_runtime import WorkspacePreferencesRuntime
    from ...services.stt import STTService
    from ...services.tts import TTSService
    from ...services.vision_service import VisionService

log = Logger.get("AGENT.GRAPH")

# Compatibility default for callers that have not been wired to runtime prefs.
TRIMMED_MESSAGE_LIMIT = DEFAULT_MAX_HISTORY_MESSAGES


class BaseAgentGraph:
    """Holds services and reusable node methods for chat agent graphs."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        seen: set[str] = set()
        for base in reversed(cls.mro()[1:]):
            for name, attr in getattr(base, "__dict__", {}).items():
                if name in seen or not _is_graph_node_method(name, attr):
                    continue
                seen.add(name)
                setattr(cls, name, wrap_graph_node(_node_label(name), attr))
        for name, attr in list(cls.__dict__.items()):
            if _is_graph_node_method(name, attr):
                setattr(cls, name, wrap_graph_node(_node_label(name), attr))

    def __init__(
        self,
        *,
        workspace_path: "Path",
        stt_service: "STTService | None",
        vision_service: "VisionService | None",
        tts_service: "TTSService | None",
        credential_store: "CredentialStore | None",
        checkpointer: Checkpointer | None,
        memory_service: "MemoryService | None" = None,
        preferences: "WorkspacePreferencesRuntime | None" = None,
        knowledge_subgraph: CompiledStateGraph | None = None,
    ) -> None:
        self._workspace_path = workspace_path
        self._stt = stt_service
        self._vision = vision_service
        self._tts = tts_service
        self._memory = memory_service
        self._credentials = credential_store
        self._checkpointer = checkpointer
        self._preferences = preferences
        # Compiled retrieval-only knowledge subgraph (KnowledgeAgentGraph.build_retrieval()).
        # None when knowledge is unavailable — the chat graph then skips the knowledge branch.
        self._knowledge_subgraph = knowledge_subgraph
        self._ledger_sink = LedgerSink(workspace_path)

    # ------------------------------------------------------------------
    # Live service swaps — used by preference / provider reactions to rebuild media
    # services without restarting the server. ``stt_node`` reads ``self._stt`` and
    # ``tts_node`` reads ``self._tts`` per call, so updating the attributes is enough;
    # chat LLM compiled-graph invalidation is handled separately in AgentManager.
    # ------------------------------------------------------------------

    def set_stt_service(self, stt_service: "STTService | None") -> None:
        self._stt = stt_service

    def set_tts_service(self, tts_service: "TTSService | None") -> None:
        self._tts = tts_service

    def set_memory_service(self, memory_service: "MemoryService | None") -> None:
        self._memory = memory_service

    def set_knowledge_subgraph(self, knowledge_subgraph: CompiledStateGraph | None) -> None:
        """Swap the compiled knowledge subgraph (rebuilt on knowledge-preference changes).

        ``knowledge_retrieve_node`` reads ``self._knowledge_subgraph`` per call, so reassigning is
        enough — no chat-graph recompile (the knowledge branch shape does not depend on prefs).
        """
        self._knowledge_subgraph = knowledge_subgraph

    # ------------------------------------------------------------------
    # Override point — subclasses wire the StateGraph here.
    # ------------------------------------------------------------------

    def build(
        self,
        *,
        model: BaseChatModel,
        tools: list,
        model_id: str,
        system_prompt: str | None,
    ) -> CompiledStateGraph:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _emit(writer: StreamWriter, name: str, payload: dict[str, Any]) -> None:
        """Push a domain event onto the custom stream (consumed by AgentManager)."""
        writer(make_event(name, payload))

    def _new_state_graph(self) -> StateGraph:
        """Allocate an empty StateGraph keyed on ``GraphState``."""
        return StateGraph(GraphState)

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    async def ingest_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        """Split the inbound UnifiedMessage into per-modality fan-out inputs.

        Bytes ride on the per-item dicts so they reach the STT/vision Send
        sub-states without polluting parent state. ``audio_items`` etc. are
        cleared by ``gather_node`` so the bytes never enter the long-lived
        checkpoint.
        """
        envelope = state.get("inbound_envelope") or {}
        msg = UnifiedMessage.model_validate(envelope) if envelope else None

        audio_items: list[AudioItem] = []
        image_items: list[ImageItem] = []
        text_inputs: list[str] = []

        if msg is not None:
            voice_input_allowed = bool(state.get("voice_input_allowed", True))
            for idx, item in enumerate(msg.content):
                if item.content_type == CONTENT_TYPE_TEXT:
                    if item.body:
                        text_inputs.append(item.body)
                elif item.content_type == CONTENT_TYPE_AUDIO and voice_input_allowed:
                    audio_items.append(
                        AudioItem(
                            item_index=idx,
                            body=item.body,
                            mime_type=str(item.metadata.get("mime_type", "audio/m4a")),
                            blob_id=item.metadata.get("blob_id"),
                            size=item.metadata.get("size"),
                            duration_ms=item.metadata.get("duration_ms"),
                        )
                    )
                elif item.content_type == CONTENT_TYPE_IMAGE:
                    image_items.append(
                        ImageItem(
                            item_index=idx,
                            body=item.body,
                            blob_id=item.metadata.get("blob_id"),
                        )
                    )
                # Other content types are skipped silently here — gather_node
                # surfaces "no usable input" if everything is dropped.

        log.info(
            "✅ ingest — %s · audio=%d image=%d text=%d",
            state.get("inbound_id", "?"),
            len(audio_items),
            len(image_items),
            len(text_inputs),
        )
        self._emit(
            writer,
            GRAPH_INGEST_COMPLETED,
            {
                "inbound_id": state.get("inbound_id", ""),
                "chat_channel_id": state.get("chat_channel_id", 0),
                "character_id": state.get("character_id", ""),
                "model_id": state.get("model_id", ""),
                "audio_count": len(audio_items),
                "image_count": len(image_items),
                "text_count": len(text_inputs),
            },
        )
        return {
            "audio_items": audio_items,
            "image_items": image_items,
            "text_inputs": text_inputs,
        }

    def dispatch_media(self, state: GraphState) -> list[Send] | str:
        """Fan out to STT and vision branches, one Send per content item.

        Returns either a list of ``Send`` objects (parallel sub-state branches
        for each media item) or the string ``"gather"`` when there is nothing
        to fan out to. The string return takes the regular edge so the parent
        state is preserved — Sends would otherwise replace state with the
        empty sub-state dict.
        """
        sends: list[Send] = []
        for item in state.get("audio_items", []) or []:
            sends.append(
                Send(
                    "stt",
                    {
                        "audio_item": item,
                        "inbound_id": state.get("inbound_id", ""),
                        "chat_channel_id": state.get("chat_channel_id", 0),
                        "routing_metadata": dict(state.get("routing_metadata") or {}),
                        "character_id": state.get("character_id", ""),
                    },
                )
            )
        for item in state.get("image_items", []) or []:
            sends.append(
                Send(
                    "vision",
                    {
                        "image_item": item,
                        "inbound_id": state.get("inbound_id", ""),
                        "chat_channel_id": state.get("chat_channel_id", 0),
                        "routing_metadata": dict(state.get("routing_metadata") or {}),
                        "character_id": state.get("character_id", ""),
                    },
                )
            )
        if sends:
            return sends
        # No fan-out branches → take the regular edge to gather with full state.
        return "gather"

    @graph_logged(captures={"usage", "decision"})
    async def stt_node(self, sub_state: dict[str, Any], writer: StreamWriter) -> dict[str, Any]:
        """Transcribe one audio item. Runs in parallel branches via Send."""
        item: AudioItem = sub_state["audio_item"]
        inbound_id = sub_state.get("inbound_id", "")
        if entry := current_entry.get():
            entry.set_input_preview(_audio_item_preview(item))
        if self._stt is None or not self._stt.is_available():
            if entry := current_entry.get():
                entry.set_decision("provider_error", "stt_unavailable")
                entry.set_error("stt_unavailable")
                entry.set_output_preview("error: stt_unavailable")
            err: NodeError = {
                "node": "stt",
                "item_index": item["item_index"],
                "error": "stt_unavailable",
            }
            self._emit(writer, GRAPH_ERROR, {
                "inbound_id": inbound_id, "node": "stt", "error": "stt_unavailable",
            })
            return {"errors": [err]}

        t0 = time.perf_counter()
        try:
            text = await self._stt.transcribe(item["body"], mime_type=item["mime_type"])
        except Exception as exc:
            if entry := current_entry.get():
                entry.set_decision("provider_error", "exception")
                entry.set_error("provider_error")
                entry.set_output_preview(f"error: {exc}")
            log.error(
                "❌ stt — %s · item=%d", inbound_id, item["item_index"],
                error=str(exc), exc_info=True,
            )
            self._emit(writer, GRAPH_ERROR, {
                "inbound_id": inbound_id, "node": "stt", "error": str(exc),
            })
            err = {"node": "stt", "item_index": item["item_index"], "error": str(exc)}
            return {"errors": [err]}

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if entry := current_entry.get():
            model_id = str(getattr(self._stt, "_default_model", "") or "")
            provider = ""
            provider_map = getattr(self._stt, "_model_to_provider", {})
            provider_obj = provider_map.get(model_id) if isinstance(provider_map, dict) else None
            if provider_obj is not None:
                provider = str(getattr(provider_obj, "name", "") or "")
            entry.add_usage(
                provider=provider,
                model=model_id,
                stt_audio_seconds=(float(item.get("duration_ms") or 0) / 1000),
            )
            entry.set_decision("transcribed" if text.strip() else "silence", provider)
            entry.set_output_preview(f"transcript: {text}" if text.strip() else "transcript: <empty>")
        log.info(
            "✅ stt — %s · item=%d", inbound_id, item["item_index"],
            elapsed_ms=elapsed_ms,
            transcript_preview=text[:120],
        )

        result: Transcript = {
            "item_index": item["item_index"],
            "transcript": text,
            "blob_id": item.get("blob_id"),
            "mime_type": item["mime_type"],
            "duration_ms": item.get("duration_ms"),
        }
        self._emit(
            writer,
            GRAPH_STT_COMPLETED,
            {
                "inbound_id": inbound_id,
                "chat_channel_id": sub_state.get("chat_channel_id", 0),
                "item_index": item["item_index"],
                "transcript": text,
            },
        )
        return {"transcripts": [result]}

    @graph_logged(captures={"decision"})
    async def vision_node(self, sub_state: dict[str, Any], writer: StreamWriter) -> dict[str, Any]:
        """Describe one image item. Runs in parallel branches via Send."""
        item: ImageItem = sub_state["image_item"]
        inbound_id = sub_state.get("inbound_id", "")
        if entry := current_entry.get():
            entry.set_input_preview(_image_item_preview(item))
        if self._vision is None or not self._vision.is_available():
            if entry := current_entry.get():
                entry.set_decision("skipped_unsupported", "vision_unavailable")
                entry.set_skipped("vision_unavailable")
                entry.set_output_preview("error: vision_unavailable")
            err: NodeError = {
                "node": "vision",
                "item_index": item["item_index"],
                "error": "vision_unavailable",
            }
            self._emit(writer, GRAPH_ERROR, {
                "inbound_id": inbound_id, "node": "vision", "error": "vision_unavailable",
            })
            return {"errors": [err]}

        t0 = time.perf_counter()
        try:
            description = await self._vision.describe(item["body"])
        except Exception as exc:
            if entry := current_entry.get():
                entry.set_decision("provider_error", "exception")
                entry.set_error("provider_error")
                entry.set_output_preview(f"error: {exc}")
            log.error(
                "❌ vision — %s · item=%d", inbound_id, item["item_index"],
                error=str(exc), exc_info=True,
            )
            self._emit(writer, GRAPH_ERROR, {
                "inbound_id": inbound_id, "node": "vision", "error": str(exc),
            })
            err = {"node": "vision", "item_index": item["item_index"], "error": str(exc)}
            return {"errors": [err]}

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if entry := current_entry.get():
            entry.set_decision("described", "image")
            entry.set_output_preview(f"description: {description}")
        log.info(
            "✅ vision — %s · item=%d", inbound_id, item["item_index"],
            elapsed_ms=elapsed_ms,
            description_preview=description[:120],
        )
        result: Vision = {
            "item_index": item["item_index"],
            "description": description,
        }
        self._emit(
            writer,
            GRAPH_VISION_COMPLETED,
            {
                "inbound_id": inbound_id,
                "chat_channel_id": sub_state.get("chat_channel_id", 0),
                "item_index": item["item_index"],
                "description": description,
            },
        )
        return {"visions": [result]}

    async def gather_node(self, state: GraphState) -> dict[str, Any]:
        """Compose ``user_text`` from text + transcripts + visions in original item order.

        Also clears ``audio_items`` / ``image_items`` so audio/image bytes
        never persist in the long-lived checkpoint.
        """
        ordered: list[tuple[int, str]] = []
        for idx, body in enumerate(state.get("text_inputs", []) or []):
            # Text passthroughs don't carry their original index; preserve
            # arrival order by giving them sortable negative keys.
            ordered.append((-1_000_000 + idx, body))
        for tr in state.get("transcripts", []) or []:
            ordered.append((tr["item_index"], tr["transcript"]))
        for vi in state.get("visions", []) or []:
            ordered.append((vi["item_index"], f"[image]: {vi['description']}"))

        ordered.sort(key=lambda p: p[0])
        text = "\n".join(p for _, p in ordered if p)
        return {
            "user_text": text or None,
            # Drop bytes from state so checkpoint stays small.
            "audio_items": [],
            "image_items": [],
        }

    def input_gate(self, state: GraphState) -> str:
        """Short-circuit when this turn produced no usable input.

        Triggered when ``gather_node`` failed to compose ``user_text`` (typical
        for audio-only inbounds whose STT branches errored). Calling the LLM
        with an unchanged message history burns the full context for nothing
        and tends to either parrot the previous reply or return empty content.
        Route to ``media_failed`` instead, which produces a canned apology.
        """
        user_text = state.get("user_text") or ""
        if user_text.strip():
            return "trim_history"
        return "media_failed"

    @graph_logged(captures={"decision"})
    async def media_failed_node(
        self, state: GraphState, writer: StreamWriter
    ) -> dict[str, Any]:
        """Emit a canned reply when this turn yielded no usable user input.

        Reached via ``input_gate`` when ``user_text`` is empty after gather.
        Sets ``reply_text`` / ``reply_id`` and emits ``graph.reply.completed``
        so downstream subscribers persist and send the fallback the same way
        they handle real LLM replies. ``tts_gate`` then decides whether to
        voice the apology based on the original ``request_voice_reply`` flag.
        """
        inbound_id = state.get("inbound_id", "")
        errs = state.get("errors", []) or []
        stt_failed = any(e.get("node") == "stt" for e in errs)
        vision_failed = any(e.get("node") == "vision" for e in errs)

        if stt_failed and vision_failed:
            reply_text = "Sorry, I couldn't process the audio or image. Please try again."
            detail = "stt_and_vision_failed"
        elif stt_failed:
            reply_text = "Sorry, I couldn't understand the audio. Please try again."
            detail = "stt_failed"
        elif vision_failed:
            reply_text = "Sorry, I couldn't process the image. Please try again."
            detail = "vision_failed"
        else:
            reply_text = (
                "Sorry, I didn't catch any content in your message. Please try again."
            )
            detail = "no_content"

        if entry := current_entry.get():
            entry.set_decision("skipped_no_input", detail)
            entry.set_input_preview(f"errors: {len(errs)}; user_text: <empty>")
            entry.set_output_preview(f"reply: {reply_text}")

        reply_id = f"reply-{uuid.uuid4()}"
        log.info(
            "⚠️ media_failed — %s · %s · len=%d",
            inbound_id, detail, len(reply_text),
        )
        self._emit(
            writer,
            GRAPH_REPLY_COMPLETED,
            {
                "inbound_id": inbound_id,
                "chat_channel_id": state.get("chat_channel_id", 0),
                "thread_id": state.get("thread_id", ""),
                "reply_text": reply_text,
                "reply_id": reply_id,
                "request_voice_reply": bool(state.get("request_voice_reply", False)),
            },
        )
        return {"reply_text": reply_text, "reply_id": reply_id}

    async def trim_history_node(self, state: GraphState) -> dict[str, Any]:
        """Trim chat history to the latest ``chat.max_messages`` turns.

        Split out of the old ``memory_in`` node so it runs *before* the parallel
        memory + knowledge branches: both consume the same trimmed window (knowledge's
        history-aware query rewrite must see exactly what memory sees).
        """
        messages: list[AnyMessage] = list(state.get("messages", []) or [])
        limit = self._history_window()
        keep = _trim_chat_history(messages, limit)
        if keep == messages:
            return {}
        from langchain_core.messages import RemoveMessage
        from langgraph.graph.message import REMOVE_ALL_MESSAGES

        log.info("trim_history - before=%d after=%d", len(messages), len(keep))
        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *keep]}

    @graph_logged(captures={"decision"})
    async def memory_search_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        """Bring recent conversation memory (mem0) into the turn. Runs after ``trim_history``."""
        text = state.get("user_text") or ""
        if entry := current_entry.get():
            entry.set_input_preview(f"search: {text}" if text.strip() else "search: <empty>")
        if not text.strip() or self._memory is None:
            if entry := current_entry.get():
                entry.set_decision("empty", "disabled" if self._memory is None else "no_query")
                entry.set_output_preview(
                    "results: 0; disabled" if self._memory is None else "results: 0; no_query"
                )
            return {}

        memory_prefs = getattr(self._current_preferences(), "memory", None)
        if not bool(getattr(memory_prefs, "enabled", False)):
            if entry := current_entry.get():
                entry.set_decision("empty", "disabled")
                entry.set_output_preview("results: 0; disabled")
            return {}
        # Independent per-direction toggle: skip retrieval when memory search is off.
        if not bool(getattr(getattr(memory_prefs, "search", None), "enabled", True)):
            if entry := current_entry.get():
                entry.set_decision("empty", "search_disabled")
                entry.set_output_preview("results: 0; search disabled")
            return {}

        t0 = time.perf_counter()
        memory_user_id = resolve_memory_user_id(
            data_user_id=state.get("data_user_id"),
            workspace_path=self._workspace_path,
        )
        try:
            hits = await self._memory.search(
                text,
                user_id=memory_user_id,
                character_id=state.get("character_id", ""),
            )
        except Exception as exc:
            if entry := current_entry.get():
                entry.set_decision("failed", _error_slug(exc))
                entry.set_error("memory_search_failed")
                entry.set_output_preview(f"error: {exc}")
            log.warning(
                "memory_search failed - %s",
                state.get("inbound_id", "?"),
                error=str(exc),
            )
            return {}

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if entry := current_entry.get():
            entry.set_decision("retrieved" if hits else "empty", str(len(hits)))
            entry.set_output_preview(_memory_results_preview("results", hits))
        log.info("memory_search retrieved - n=%d", len(hits), elapsed_ms=elapsed_ms)
        self._emit(
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
        if self._knowledge_subgraph is not None and bool(state.get("knowledge_enabled", True)):
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
        entry = current_entry.get()
        if self._knowledge_subgraph is None:
            if entry:
                entry.set_decision("skipped", "no_subgraph")
                entry.set_output_preview("sources: 0; no_subgraph")
            return {}
        user_text = (state.get("user_text") or "").strip()
        if not user_text:
            if entry:
                entry.set_decision("empty", "no_user_text")
                entry.set_output_preview("sources: 0; no_user_text")
            return {}
        if entry:
            entry.set_input_preview(f"query: {user_text[:160]}")

        retrieval = self._current_preferences().knowledge.retrieval
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
        substep_token = current_substep.set(entry.step_index) if entry is not None else None
        try:
            out = await self._knowledge_subgraph.ainvoke(sub_input)
        except Exception as exc:
            log.warning(
                "⚠️ knowledge_retrieve failed - %s",
                state.get("inbound_id", "?"),
                error=str(exc),
                exc_info=True,
            )
            if entry:
                entry.set_decision("failed", _error_slug(exc))
                entry.set_error("knowledge_retrieve_failed")
                entry.set_output_preview(f"error: {exc}")
            return {}
        finally:
            if substep_token is not None:
                current_substep.reset(substep_token)

        sources = list(out.get("sources") or [])
        context = out.get("context") or ""
        if entry:
            entry.set_decision("retrieved" if sources else "empty", str(len(sources)))
            entry.set_output_preview(f"sources: {len(sources)}")
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

    def make_compose_context_node(self):
        """Return a node that assembles the ephemeral per-turn context block.

        Renders memory + knowledge (+ citation instruction) via :class:`ContextAssembler` into
        ``turn_context``. Persona is NOT included — it stays a stable system message in
        ``call_model`` (cache-friendly). Runs once before the tools loop; ``call_model`` injects
        ``turn_context`` into the current user turn each iteration. Nothing here touches ``messages``.
        """
        assembler = ContextAssembler()  # Phase 1: no token budget (seam for Phase 2).

        @graph_logged(captures={"decision"})
        async def compose_context(state: GraphState, writer: StreamWriter) -> dict[str, Any]:
            sources = state.get("knowledge_sources") or []
            # Instructions, Knowledge, and Memories are always present (sections render a
            # placeholder when empty); the citation instruction is conditional. Knowledge renders
            # from the structured sources (tagged, neutralized), not the pre-joined string.
            blocks = [
                block
                for block in (
                    instructions_block(self._chat_instructions()),
                    knowledge_block(sources),
                    memory_block(state.get("retrieved_memories") or []),
                    citation_block(
                        has_sources=bool(sources),
                        cite_enabled=self._knowledge_cite_in_chat(),
                    ),
                )
                if block is not None
            ]
            turn_context = assembler.assemble(blocks=blocks)
            if entry := current_entry.get():
                sources = ",".join(block.source for block in blocks) or "none"
                entry.set_decision("composed", sources)
                entry.set_output_preview(f"blocks: {sources}; chars={len(turn_context)}")
            return {"turn_context": turn_context}

        return self._wrap_dynamic_node("compose_context", compose_context)

    def make_call_model_node(
        self,
        *,
        model: BaseChatModel,
        tools: list,
        model_id: str,
        system_prompt: str | None,
    ):
        """Return a closed-over ``call_model`` node bound to this character/model."""
        bound = model.bind_tools(tools) if tools else model

        @graph_logged(captures={"usage", "decision"})
        async def call_model(state: GraphState, writer: StreamWriter) -> dict[str, Any]:
            messages: list[AnyMessage] = list(state.get("messages", []) or [])
            if not messages:
                if entry := current_entry.get():
                    entry.set_decision("empty", "no_messages")
                    entry.set_input_preview("messages: 0")
                    entry.set_output_preview("reply: <empty>")
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
                        user_text = _normalize_reply_content(inputs[i].content)
                        inputs[i] = HumanMessage(
                            content=f"{turn_context}\n\n## Last User Message\n{user_text}"
                        )
                        break
            if system_prompt:
                inputs = [SystemMessage(content=system_prompt), *inputs]
            if entry := current_entry.get():
                # Preview the clean stored turn (not the enriched copy) so the ledger reflects state.
                entry.set_input_preview(f"text: {_last_human_message_preview(messages)}")
            input_estimate = count_tokens_approximately(inputs)
            log.fineinfo(
                "call_model — input · count=%d tokens≈%d",
                len(inputs), input_estimate,
            )
            response = await bound.ainvoke(inputs)
            usage_payload = _llm_usage_payload(
                response,
                inbound_id=state.get("inbound_id", ""),
                chat_channel_id=int(state.get("chat_channel_id") or 0),
                model_id=model_id or str(state.get("model_id") or ""),
                estimated_input_tokens=input_estimate,
            )
            if entry := current_entry.get():
                effective_model = model_id or str(state.get("model_id") or "")
                provider = effective_model.split(":", 1)[0] if ":" in effective_model else ""
                entry.add_usage(
                    provider=provider,
                    model=effective_model,
                    input_tokens=int(usage_payload.get("input_tokens") or input_estimate or 0),
                    output_tokens=int(usage_payload.get("output_tokens") or 0),
                    cached_input_tokens=int(usage_payload.get("cached_input_tokens") or 0),
                    reasoning_tokens=int(usage_payload.get("reasoning_tokens") or 0),
                )
                decision_kind, decision_detail = _llm_decision(response)
                entry.set_decision(decision_kind, decision_detail)
                reply_preview = _normalize_reply_content(response.content)
                entry.set_output_preview(
                    f"reply: {reply_preview}"
                    if reply_preview.strip()
                    else _tool_calls_preview(getattr(response, "tool_calls", None) or [])
                )
            self._emit(
                writer,
                GRAPH_LLM_USAGE,
                usage_payload,
            )
            return {"messages": [response]}

        return self._wrap_dynamic_node("call_model", call_model)

    def make_tools_node(self, tools: list):
        """Return a ToolNode-compatible node that emits compact telemetry."""
        tools_by_name = {getattr(tool, "name", ""): tool for tool in tools}

        @graph_logged(captures={"decision"}, flush=False)
        async def tools_node(state: GraphState, writer: StreamWriter) -> dict[str, Any]:
            messages: list[AnyMessage] = list(state.get("messages", []) or [])
            if not messages:
                return {}
            last = messages[-1]
            if not isinstance(last, AIMessage) or not last.tool_calls:
                return {}

            out: list[ToolMessage] = []
            parent_entry = current_entry.get()
            for idx, call in enumerate(last.tool_calls):
                tool_call_id = _tool_call_id(call)
                tool_name = _tool_call_name(call)
                args = _tool_call_args(call)
                tool = tools_by_name.get(tool_name)
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
                if parent_entry is not None:
                    child = parent_entry.spawn_child(
                        node=f"tools/{_error_slug(tool_name) or 'unknown'}",
                        status="ok" if status == "completed" else "error",
                        elapsed_ms=elapsed_ms,
                        branch_index=idx,
                    )
                    child.set_input_preview(_tool_input_preview(tool_name, args))
                    child.set_output_preview(
                        f"result: {content}" if status == "completed" else f"error: {error}"
                    )
                    if status == "completed":
                        child.set_decision("ok", "ok")
                    else:
                        child.set_decision("client_error", _error_slug(error or "tool_error"))
                        child.set_error("tool_error")
                self._emit(
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

        return self._wrap_dynamic_node("tools", tools_node)

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
            reply_text = _normalize_reply_content(msgs[-1].content)

        if entry := current_entry.get():
            entry.set_input_preview(
                f"user: {state.get('user_text') or ''}; assistant: {reply_text}"
            )

        if not reply_text:
            if entry := current_entry.get():
                entry.set_output_preview("error: empty_reply")
            log.warning(
                "⚠️ memory_out — empty reply · %s",
                state.get("inbound_id", "?"),
            )
            self._emit(writer, GRAPH_ERROR, {
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
        self._emit(
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
        if self._tts is None or not self._tts.is_available():
            return "finalize"
        return "tts"

    async def _store_turn_memory(
        self,
        state: GraphState,
        writer: StreamWriter,
        reply_text: str,
    ) -> None:
        memory_prefs = self._current_preferences().memory
        if self._memory is None or not bool(getattr(memory_prefs, "enabled", False)):
            if entry := current_entry.get():
                entry.set_decision("skipped", "disabled")
                entry.set_output_preview("stored: 0; disabled")
            return
        # Independent per-direction toggle: skip storage when memory extraction is off (read-only).
        if not bool(getattr(getattr(memory_prefs, "extraction", None), "enabled", True)):
            if entry := current_entry.get():
                entry.set_decision("skipped", "extraction_disabled")
                entry.set_output_preview("stored: 0; extraction disabled")
            return

        t0 = time.perf_counter()
        memory_user_id = resolve_memory_user_id(
            data_user_id=state.get("data_user_id"),
            workspace_path=self._workspace_path,
        )
        memory_run_id = str(state.get("chat_channel_id") or state.get("thread_id") or "")
        try:
            result = await self._memory.add(
                f"User: {state.get('user_text') or ''}\nAssistant: {reply_text}",
                user_id=memory_user_id,
                run_id=memory_run_id,
                character_id=state.get("character_id", ""),
                metadata={
                    "thread_id": state.get("thread_id", ""),
                    "channel_id": state.get("chat_channel_id", 0),
                    "source": "conversation",
                },
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            if entry := current_entry.get():
                entry.set_decision("failed", _error_slug(exc))
                entry.set_error("memory_store_failed")
                entry.set_output_preview(f"error: {exc}")
            log.warning(
                "❌ memory_out — store failed · %s",
                state.get("inbound_id", "?"),
                error=str(exc),
                elapsed_ms=elapsed_ms,
                exc_info=True,
            )
            return

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        usage = result.usage
        stored_count = result.stored_count
        # Detect mem0 silently dropping the response (e.g. extraction LLM
        # produced output but mem0's parser failed) so the ledger row reflects
        # reality instead of always claiming "stored". An LLM was clearly
        # invoked but nothing landed in the vector store.
        extraction_dropped = stored_count == 0 and usage is not None and usage.call_count > 0
        # Attribute mem0's internal LLM calls to this node's ledger row. The
        # ``RunAccumulator`` keeps headline ``model`` from ``call_model`` only,
        # so recording a different provider/model here does not pollute the
        # run summary; row-level ``_with_cost`` prices it independently.
        if entry := current_entry.get():
            if extraction_dropped:
                entry.set_decision("failed", "extraction_dropped")
                entry.set_error("memory_extraction_dropped")
            elif stored_count == 0:
                entry.set_decision("stored", "no_new_facts")
            else:
                entry.set_decision("stored", "ok")
            entry.set_output_preview(
                _memory_results_preview(
                    "stored",
                    list(getattr(result, "stored_items", ()) or []),
                    stored_count,
                )
            )
            if usage is not None:
                entry.add_usage(
                    provider=usage.provider,
                    model=usage.model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cached_input_tokens=usage.cached_input_tokens,
                    reasoning_tokens=usage.reasoning_tokens,
                )
        if extraction_dropped:
            log.warning(
                "⚠️ memory_out — extraction dropped · %s · %dms",
                state.get("inbound_id", "?"),
                elapsed_ms,
                input_tokens=getattr(usage, "input_tokens", 0),
                output_tokens=getattr(usage, "output_tokens", 0),
                llm_calls=getattr(usage, "call_count", 0),
            )
        else:
            log.info(
                "✅ memory_out — stored · %s · %dms",
                state.get("inbound_id", "?"),
                elapsed_ms,
                stored=stored_count,
                input_tokens=getattr(usage, "input_tokens", 0),
                output_tokens=getattr(usage, "output_tokens", 0),
                llm_calls=getattr(usage, "call_count", 0),
            )
        self._emit(
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
        if entry := current_entry.get():
            entry.set_input_preview(f"text: {text}" if text else "text: <empty>")
        if not text:
            if entry := current_entry.get():
                entry.set_decision("skipped_no_text", "empty")
                entry.set_skipped("empty")
                entry.set_output_preview("audio: skipped empty")
            return {}

        from ...domain.character import load_character_from_disk
        from ...domain.preferences import resolve_character_voice

        try:
            ch = load_character_from_disk(self._workspace_path, state.get("character_id", ""))
        except FileNotFoundError as exc:
            if entry := current_entry.get():
                entry.set_decision("skipped_no_voice", "character_missing")
                entry.set_skipped("character_missing")
                entry.set_output_preview("audio: skipped character_missing")
            self._emit(writer, GRAPH_ERROR, {
                "inbound_id": inbound_id, "node": "tts", "error": str(exc),
            })
            return {}

        prefs = self._current_preferences()
        resolved = resolve_character_voice(
            ch.voice_models,
            prefs,
            self._workspace_path,
            credential_store=self._credentials,
            tts_instructions=ch.tts_instructions,
            tts_voice_by_provider=dict(ch.tts_voice_by_provider),
        )
        if resolved is None:
            if entry := current_entry.get():
                entry.set_decision("skipped_no_voice", "voice_unresolved")
                entry.set_skipped("voice_unresolved")
                entry.set_output_preview("audio: skipped voice_unresolved")
            log.warning(
                "⚠️ tts — %s · no_voice_resolved (set character voice_models / llm.default_tts)",
                inbound_id,
            )
            self._emit(writer, GRAPH_ERROR, {
                "inbound_id": inbound_id, "node": "tts", "error": "no_voice_resolved",
            })
            return {}

        t0 = time.perf_counter()
        try:
            result = await self._tts.synthesize(  # type: ignore[union-attr]
                text,
                model=resolved.model,
                voice=resolved.voice,
                instructions=resolved.instructions,
            )
        except Exception as exc:
            if entry := current_entry.get():
                entry.set_decision("provider_error", "exception")
                entry.set_error("provider_error")
                entry.set_output_preview(f"error: {exc}")
            log.error("❌ tts — %s", inbound_id, error=str(exc), exc_info=True)
            self._emit(writer, GRAPH_ERROR, {
                "inbound_id": inbound_id, "node": "tts", "error": str(exc),
            })
            return {}

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        log.info(
            "✅ tts — %s · bytes=%d · model=%s",
            inbound_id, len(result.audio_bytes), result.model,
            elapsed_ms=elapsed_ms,
        )

        # Persistence + outbound envelope construction live in the
        # CommManager-side subscriber. The graph node only emits the audio
        # bytes (base64) and the model/voice metadata.
        import base64

        audio_b64 = base64.b64encode(result.audio_bytes).decode()
        reply_id = state.get("reply_id") or ""
        duration_ms = result.duration_ms
        provider = str(getattr(result, "provider", "") or "")
        usage_metadata = getattr(result, "usage_metadata", None)
        if not isinstance(usage_metadata, dict):
            usage_metadata = {}
        metered_text = text
        if provider == "openai" and result.model == "gpt-4o-mini-tts" and resolved.instructions:
            metered_text = f"{resolved.instructions}\n{text}"
        # Gemini TTS prices off ``usageMetadata`` text/audio modality tokens (see
        # ``docs/model_pricing.md``); persist them on the ledger so ``_with_cost``
        # can call ``estimate_tts_usage_cost`` for Google models. OpenAI providers
        # do not return these — leave at 0 so the catalog falls back to ``input_tokens``.
        tts_text_tokens = modality_token_count(
            usage_metadata,
            detail_keys=("promptTokensDetails", "prompt_tokens_details"),
            modality="TEXT",
        )
        tts_audio_tokens = modality_token_count(
            usage_metadata,
            detail_keys=("candidatesTokensDetails", "candidates_tokens_details"),
            modality="AUDIO",
        )
        tts_text_tokens, tts_audio_tokens = gemini_usage_aggregate_fallback(
            usage_metadata,
            input_text_tokens=tts_text_tokens,
            output_audio_tokens=tts_audio_tokens,
        )
        if entry := current_entry.get():
            entry.add_usage(
                provider=provider,
                model=result.model,
                input_tokens=_estimate_text_tokens(metered_text),
                tts_chars=len(text),
                tts_text_tokens=tts_text_tokens or None,
                tts_audio_tokens=tts_audio_tokens or None,
                tts_audio_seconds=(
                    duration_ms / 1000 if isinstance(duration_ms, (int, float)) else 0.0
                ),
            )
            entry.set_decision("voiced", provider)
            entry.set_output_preview(
                f"audio: {len(result.audio_bytes)} bytes; duration_ms={duration_ms}; model={result.model}"
            )
        payload = {
            "inbound_id": inbound_id,
            "chat_channel_id": state.get("chat_channel_id", 0),
            "reply_id": reply_id,
            "blob_id": "",  # filled by subscriber after disk write + hash
            "media_type": result.mime_type,
            "size": len(result.audio_bytes),
            "duration_ms": duration_ms,
            "audio_b64": audio_b64,
            "provider": provider,
            "model": result.model,
            "voice": result.voice,
            "input_characters": len(text),
            "input_text_tokens": _estimate_text_tokens(metered_text),
            "generated_audio_seconds": (
                duration_ms / 1000 if isinstance(duration_ms, (int, float)) else 0.0
            ),
            "usage_metadata": usage_metadata,
        }
        self._emit(writer, GRAPH_TTS_COMPLETED, payload)

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
        if entry := current_entry.get():
            entry.set_input_preview(
                f"reply_id: {reply_id or '<empty>'}; reply: {reply_text}"
            )
        if reply_text and reply_id:
            if entry := current_entry.get():
                entry.set_decision("completed", "ok")
                entry.set_output_preview("run: completed")
            self._emit(
                writer,
                GRAPH_RUN_COMPLETED,
                {
                    "inbound_id": inbound_id,
                    "chat_channel_id": chat_channel_id,
                    "reply_id": reply_id,
                },
            )
            return {}

        if entry := current_entry.get():
            entry.set_decision("failed", "reply_generation_failed")
            entry.set_error("reply_generation_failed")
            entry.set_output_preview("run: failed reply_generation_failed")
        self._emit(
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

    def _current_preferences(self):
        if self._preferences is not None:
            return self._preferences.current
        from ...domain.preferences import load_preferences

        return load_preferences(self._workspace_path)

    def _history_window(self) -> int:
        try:
            return int(self._current_preferences().chat.max_messages)
        except Exception:
            return TRIMMED_MESSAGE_LIMIT

    def _knowledge_cite_in_chat(self) -> bool:
        try:
            return bool(self._current_preferences().chat.cite_sources)
        except Exception:
            return False

    def _chat_instructions(self) -> str:
        try:
            return str(self._current_preferences().chat.instructions or "")
        except Exception:
            return ""

    def _reply_knowledge_sources(self, state: GraphState) -> list[dict[str, Any]]:
        """Serialized knowledge sources to attach to the reply — only when chat citations are on."""
        if not self._knowledge_cite_in_chat():
            return []
        return _serialize_knowledge_sources(state.get("knowledge_sources") or [])

    def _wrap_dynamic_node(self, node_name: str, fn):
        return wrap_graph_callable(self, node_name, fn)


# ---------------------------------------------------------------------------
# Module-level helpers (no state needed, hence not methods)
# ---------------------------------------------------------------------------


def _is_graph_node_method(name: str, attr: Any) -> bool:
    if name.startswith("_") or not callable(attr):
        return False
    return name.endswith("_node") or name.startswith("node_")


def _node_label(name: str) -> str:
    if name.endswith("_node"):
        return name[: -len("_node")]
    if name.startswith("node_"):
        return name[len("node_") :]
    return name


def _error_slug(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    return "".join(ch for ch in text if ch.isalnum() or ch in {"_", "-", ".", "/"})[:80]


def _llm_decision(message: AIMessage) -> tuple[str, str]:
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        return "tool_call", _tool_call_name(tool_calls[0])
    content = _normalize_reply_content(message.content)
    if content.strip():
        return "text_reply", "ok"
    return "empty", "no_content"


def _normalize_reply_content(content: Any) -> str:
    """Convert LangChain/provider message content into Hiro's plain-text body."""
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            parts.append(str(block))
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
            continue
        cv = block.get("content")
        if isinstance(cv, str):
            parts.append(cv)
    return "\n".join(p for p in parts if p)


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
        text = _normalize_reply_content(message.content).strip()
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
        return f"{label}: {total}; " + " | ".join(snippets)
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
            return _normalize_reply_content(message.content)
    return _normalize_reply_content(messages[-1].content) if messages else ""


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


def _audio_item_preview(item: AudioItem) -> str:
    seconds = ""
    duration_ms = item.get("duration_ms")
    if isinstance(duration_ms, (int, float)) and duration_ms > 0:
        seconds = f"; duration_s={duration_ms / 1000:.2f}"
    size = item.get("size")
    size_text = f"; bytes={size}" if isinstance(size, int) and size > 0 else ""
    return f"audio item {item.get('item_index')}; mime={item.get('mime_type')}{size_text}{seconds}"


def _image_item_preview(item: ImageItem) -> str:
    blob = item.get("blob_id") or ""
    return f"image item {item.get('item_index')}" + (f"; blob={blob}" if blob else "")


def _trim_chat_history(messages: list[AnyMessage], limit: int) -> list[AnyMessage]:
    """Return a bounded chat suffix that does not start inside a tool exchange."""
    if limit <= 0:
        return []
    keep = list(messages[-limit:])
    while keep and not isinstance(keep[0], HumanMessage):
        keep.pop(0)
    return keep


def _llm_usage_payload(
    message: AIMessage,
    *,
    inbound_id: str,
    chat_channel_id: int,
    model_id: str,
    estimated_input_tokens: int,
) -> dict[str, Any]:
    usage = _usage_from_metadata(message.usage_metadata or {})
    payload: dict[str, Any] = {
        "inbound_id": inbound_id,
        "chat_channel_id": chat_channel_id,
        "model_id": model_id,
        "usage_available": bool(usage),
    }
    if usage:
        payload.update(usage)
    else:
        payload["estimated_input_tokens"] = estimated_input_tokens
    return payload


def _usage_from_metadata(raw: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = _int_token(raw.get(key))
        if value is not None:
            out[key] = value

    input_details = raw.get("input_token_details")
    if isinstance(input_details, dict):
        cached = _int_token(input_details.get("cache_read"))
        if cached is not None:
            out["cached_input_tokens"] = cached

    output_details = raw.get("output_token_details")
    if isinstance(output_details, dict):
        reasoning = _int_token(output_details.get("reasoning"))
        if reasoning is not None:
            out["reasoning_tokens"] = reasoning

    return out


def _int_token(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _estimate_text_tokens(text: str) -> int:
    stripped = str(text or "")
    if not stripped:
        return 0
    return max(1, math.ceil(len(stripped) / 4))


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
