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
import time
import uuid
from typing import TYPE_CHECKING, Any

from hiro_channel_sdk.constants import (
    CONTENT_TYPE_AUDIO,
    CONTENT_TYPE_IMAGE,
    CONTENT_TYPE_TEXT,
)
from hiro_channel_sdk.models import UnifiedMessage
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

from ...domain.preferences import DEFAULT_MEMORY_MAX_MESSAGES
from .events import (
    GRAPH_ERROR,
    GRAPH_INGEST_COMPLETED,
    GRAPH_LLM_USAGE,
    GRAPH_REPLY_COMPLETED,
    GRAPH_STT_COMPLETED,
    GRAPH_TOOL_COMPLETED,
    GRAPH_TTS_COMPLETED,
    GRAPH_VISION_COMPLETED,
    make_event,
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
    from ...runtime.preferences_runtime import WorkspacePreferencesRuntime
    from ...services.stt import STTService
    from ...services.tts import TTSService
    from ...services.vision_service import VisionService

log = Logger.get("AGENT.GRAPH")

# Compatibility default for callers that have not been wired to runtime prefs.
TRIMMED_MESSAGE_LIMIT = DEFAULT_MEMORY_MAX_MESSAGES


class BaseAgentGraph:
    """Holds services and reusable node methods for chat agent graphs."""

    def __init__(
        self,
        *,
        workspace_path: "Path",
        stt_service: "STTService | None",
        vision_service: "VisionService | None",
        tts_service: "TTSService | None",
        credential_store: "CredentialStore | None",
        checkpointer: Checkpointer | None,
        preferences: "WorkspacePreferencesRuntime | None" = None,
    ) -> None:
        self._workspace_path = workspace_path
        self._stt = stt_service
        self._vision = vision_service
        self._tts = tts_service
        self._credentials = credential_store
        self._checkpointer = checkpointer
        self._preferences = preferences

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
                    },
                )
            )
        if sends:
            return sends
        # No fan-out branches → take the regular edge to gather with full state.
        return "gather"

    async def stt_node(self, sub_state: dict[str, Any], writer: StreamWriter) -> dict[str, Any]:
        """Transcribe one audio item. Runs in parallel branches via Send."""
        item: AudioItem = sub_state["audio_item"]
        inbound_id = sub_state.get("inbound_id", "")
        if self._stt is None or not self._stt.is_available():
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

    async def vision_node(self, sub_state: dict[str, Any], writer: StreamWriter) -> dict[str, Any]:
        """Describe one image item. Runs in parallel branches via Send."""
        item: ImageItem = sub_state["image_item"]
        inbound_id = sub_state.get("inbound_id", "")
        if self._vision is None or not self._vision.is_available():
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

    async def memory_in_node(self, state: GraphState) -> dict[str, Any]:
        """Trim chat history to the latest ``TRIMMED_MESSAGE_LIMIT`` messages.

        Replaces the prior ``trimming_agent_graph``: same fixed-window memory,
        now expressed as a graph node like everything else.
        """
        messages: list[AnyMessage] = list(state.get("messages", []) or [])
        limit = self._memory_max_messages()
        if len(messages) <= limit:
            return {}
        from langchain_core.messages import RemoveMessage
        from langgraph.graph.message import REMOVE_ALL_MESSAGES

        keep = messages[-limit:]
        log.info(
            "✅ memory_in — trim · before=%d after=%d",
            len(messages), len(keep),
        )
        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *keep]}

    async def context_build_node(self, state: GraphState) -> dict[str, Any]:
        """Append the new user turn to the (trimmed) message history."""
        text = state.get("user_text")
        if not text:
            # No usable input — leave messages untouched; call_model will short-circuit.
            return {}
        return {"messages": [HumanMessage(content=text)]}

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

        async def call_model(state: GraphState, writer: StreamWriter) -> dict[str, Any]:
            messages: list[AnyMessage] = list(state.get("messages", []) or [])
            if not messages:
                return {}
            inputs: list[AnyMessage] = (
                [SystemMessage(content=system_prompt), *messages]
                if system_prompt
                else messages
            )
            input_estimate = count_tokens_approximately(inputs)
            log.fineinfo(
                "call_model — input · count=%d tokens≈%d",
                len(inputs), input_estimate,
            )
            response = await bound.ainvoke(inputs)
            self._emit(
                writer,
                GRAPH_LLM_USAGE,
                _llm_usage_payload(
                    response,
                    inbound_id=state.get("inbound_id", ""),
                    chat_channel_id=int(state.get("chat_channel_id") or 0),
                    model_id=model_id or str(state.get("model_id") or ""),
                    estimated_input_tokens=input_estimate,
                ),
            )
            return {"messages": [response]}

        return call_model

    def make_tools_node(self, tools: list):
        """Return a ToolNode-compatible node that emits compact telemetry."""
        tools_by_name = {getattr(tool, "name", ""): tool for tool in tools}

        async def tools_node(state: GraphState, writer: StreamWriter) -> dict[str, Any]:
            messages: list[AnyMessage] = list(state.get("messages", []) or [])
            if not messages:
                return {}
            last = messages[-1]
            if not isinstance(last, AIMessage) or not last.tool_calls:
                return {}

            out: list[ToolMessage] = []
            for call in last.tool_calls:
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
                    },
                )
                out.append(
                    ToolMessage(
                        content=content,
                        tool_call_id=tool_call_id or tool_name,
                    )
                )

            return {"messages": out}

        return tools_node

    def should_continue(self, state: GraphState) -> str:
        """Tools-loop conditional edge: route to ``tools`` when the LLM asked for one."""
        msgs = state.get("messages", []) or []
        if not msgs:
            return "memory_out"
        last = msgs[-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return "memory_out"

    async def memory_out_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        """Finalize the reply text and emit ``reply.completed``.

        Memory write is implicit: ``messages`` is checkpointed by LangGraph at
        the end of the super-step. This node's main job is to surface the
        normalized reply text and announce it to subscribers.
        """
        msgs = state.get("messages", []) or []
        reply_text = ""
        if msgs:
            reply_text = _normalize_reply_content(msgs[-1].content)

        if not reply_text:
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
            },
        )
        return {"reply_text": reply_text, "reply_id": reply_id}

    def tts_gate(self, state: GraphState) -> str:
        """Decide whether to enter the TTS branch after the reply completes."""
        if not state.get("reply_text"):
            return "__end__"
        if not state.get("request_voice_reply"):
            return "__end__"
        if self._tts is None or not self._tts.is_available():
            return "__end__"
        return "tts"

    async def tts_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        """Synthesize speech for ``reply_text`` and emit ``tts.completed``.

        Audio bytes are passed through the event payload as base64 (the same
        wire shape ``message.voiced`` already used today). The persistence
        subscriber on the CommManager side writes the attachment row and the
        media file from the event.
        """
        text = state.get("reply_text") or ""
        inbound_id = state.get("inbound_id", "")
        if not text:
            return {}

        from ...domain.character import load_character_from_disk
        from ...domain.preferences import resolve_character_voice

        try:
            ch = load_character_from_disk(self._workspace_path, state.get("character_id", ""))
        except FileNotFoundError as exc:
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
        payload = {
            "inbound_id": inbound_id,
            "chat_channel_id": state.get("chat_channel_id", 0),
            "reply_id": reply_id,
            "blob_id": "",  # filled by subscriber after disk write + hash
            "media_type": result.mime_type,
            "size": len(result.audio_bytes),
            "duration_ms": result.duration_ms,
            "audio_b64": audio_b64,
            "model": result.model,
            "voice": result.voice,
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

    def _current_preferences(self):
        if self._preferences is not None:
            return self._preferences.current
        from ...domain.preferences import load_preferences

        return load_preferences(self._workspace_path)

    def _memory_max_messages(self) -> int:
        try:
            return int(self._current_preferences().memory.max_messages)
        except Exception:
            return TRIMMED_MESSAGE_LIMIT


# ---------------------------------------------------------------------------
# Module-level helpers (no state needed, hence not methods)
# ---------------------------------------------------------------------------


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
    return None


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
