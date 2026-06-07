"""GraphState — per-turn state for the agent graph.

Design constraints:
  - **Bytes never live in the parent (checkpointed) state.** The fan-out
    branches (STT / vision) carry per-item bodies through ``langgraph.types.Send``
    sub-states only. The parent state stores enriched outputs (transcripts,
    descriptions) and the LangChain ``messages`` list that drives memory.
  - **Reducers concatenate parallel branch outputs** so two STT items running
    in parallel cannot race on the parent dict.
  - **Long-term checkpoint surface = ``messages`` only** (LangChain
    ``BaseMessage`` list trimmed by the memory node). Other fields are
    per-turn scratch.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AudioItem(TypedDict):
    """Audio content item carried into the STT fan-out branch only."""

    item_index: int
    body: str
    mime_type: str
    blob_id: str | None
    size: int | None
    duration_ms: int | None


class ImageItem(TypedDict):
    """Image content item carried into the vision fan-out branch only."""

    item_index: int
    body: str
    blob_id: str | None


class Transcript(TypedDict):
    """STT result merged back into parent state."""

    item_index: int
    transcript: str
    blob_id: str | None
    mime_type: str
    duration_ms: int | None


class Vision(TypedDict):
    """Vision-model description merged back into parent state."""

    item_index: int
    description: str


class NodeError(TypedDict):
    """Per-node failure surfaced through the error reducer."""

    node: str
    item_index: int | None
    error: str


class ReplyAudio(TypedDict):
    """Reference to TTS-generated audio attached to the reply."""

    blob_id: str
    media_type: str
    size: int
    duration_ms: int | None
    media_path: str
    audio_b64: str


class GraphState(TypedDict, total=False):
    """Single state schema for the chat agent graph.

    All non-checkpoint fields are per-turn scratch and may be ``None`` /
    empty between runs of the same thread. Only ``messages`` survives in
    the LangGraph checkpointer across turns.
    """

    # Inputs (set by ingest)
    inbound_id: str
    chat_channel_id: int
    thread_id: str
    character_id: str
    data_user_id: int
    model_id: str
    request_voice_reply: bool
    voice_input_allowed: bool
    # Tools kill-switch (default on): chat.tools_enabled preference AND the per-chat disable_tools
    # opt-out, combined in AgentManager. When off, call_model invokes the un-bound model so the
    # agent emits no tool calls this turn.
    tools_enabled: bool

    # Per-turn fan-out inputs (cleared after gather; never long-lived)
    audio_items: list[AudioItem]
    image_items: list[ImageItem]
    text_inputs: list[str]

    # Per-turn fan-out outputs (reducer-merged from parallel branches)
    transcripts: Annotated[list[Transcript], operator.add]
    visions: Annotated[list[Vision], operator.add]
    errors: Annotated[list[NodeError], operator.add]

    # Built by context_build / call_model
    user_text: str | None
    retrieved_memories: list[dict[str, Any]]
    # Knowledge retrieval (per-turn scratch). ``knowledge_enabled`` is the per-message toggle
    # (default on, sent in routing.metadata like request_voice_reply). ``knowledge_context`` is the
    # numbered [n] block built by the retrieval subgraph; ``knowledge_sources`` backs citations + UI.
    knowledge_enabled: bool
    knowledge_context: str | None
    knowledge_sources: list[Any]
    # Ephemeral, rebuilt every turn by compose_context: memory + knowledge (+ citation) rendered
    # into one context string. call_model injects it into the current user turn (context first,
    # question last); persona stays a separate stable system message. Never written into
    # ``messages`` (durable history stays clean). Overwritten each turn — checkpointing is harmless.
    turn_context: str | None
    messages: Annotated[list[BaseMessage], add_messages]
    reply_text: str | None
    # ``reply_id`` is set by ``memory_out_node`` and consumed by ``tts_node``
    # to address its persisted reply row; it must be declared here so LangGraph
    # keeps it on the parent state across the memory_out → tts hop. (Unknown
    # TypedDict keys are silently dropped during state merges.)
    reply_id: str | None

    # Voice
    reply_audio: ReplyAudio | None

    # Bookkeeping
    routing_metadata: dict[str, Any]
    inbound_envelope: dict[str, Any]  # serialized UnifiedMessage for subscribers
