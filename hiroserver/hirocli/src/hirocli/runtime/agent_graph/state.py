"""GraphState — per-turn state for the agent graph."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

# Runtime import (NOT TYPE_CHECKING): LangGraph calls ``get_type_hints`` on this state
# TypedDict to build its channels, which evaluates the annotation — so ``KnowledgeSource``
# must resolve at runtime even though ``from __future__ import annotations`` is on.
from hirocli.services.knowledge.models import KnowledgeSource


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


class SttSend(TypedDict):
    """Sub-state for one parallel STT branch (carried on langgraph.types.Send).

    NOT a checkpoint channel — a per-branch payload. Identity fields are copied in so the
    ledger (``_identity_from_state``) can attribute the branch row to the turn.
    """

    audio_item: AudioItem
    inbound_id: str
    chat_channel_id: int
    character_id: str
    routing_metadata: dict[str, Any]


class VisionSend(TypedDict):
    """Sub-state for one parallel vision branch (see SttSend)."""

    image_item: ImageItem
    inbound_id: str
    chat_channel_id: int
    character_id: str
    routing_metadata: dict[str, Any]


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

    Invariants (LangGraph channel semantics — keep this schema **flat**):

    1. **Checkpoint surface = ``messages`` only.** Every other field is per-turn scratch,
       overwritten each turn; its cross-turn value is undefined.
    2. **Reducer fields (``messages``, ``transcripts``, ``visions``, ``errors``) must stay
       top-level** — LangGraph keys reducers on channels; nesting them breaks parallel
       ``Send`` merges (default dict-overwrite loses data or raises ``InvalidUpdateError``).
    3. **Bytes never enter the checkpoint** — audio/image bodies ride ``Send`` sub-states only;
       ``gather_node`` clears ``audio_items`` / ``image_items``.
    """

    # --- Inputs (write-once) ---
    inbound_id: str
    chat_channel_id: int
    thread_id: str
    character_id: str
    data_user_id: int
    model_id: str
    request_voice_reply: bool
    voice_input_allowed: bool
    tools_enabled: bool

    # --- Fan-out scratch (reducer-merged) ---
    audio_items: list[AudioItem]
    image_items: list[ImageItem]
    text_inputs: list[str]
    transcripts: Annotated[list[Transcript], operator.add]
    visions: Annotated[list[Vision], operator.add]
    errors: Annotated[list[NodeError], operator.add]

    # --- Retrieval scratch (parallel) ---
    user_text: str | None
    retrieved_memories: list[dict[str, Any]]
    # Draft grounding note from the agentic recall loop (Phase 2). Produced by memory_recall/recall;
    # consumed by the persona prompt in Phase 4 (a `search_conclusion` block). None when the loop
    # abstained or found nothing.
    memory_draft: str | None
    knowledge_enabled: bool
    knowledge_context: str | None
    knowledge_sources: list[KnowledgeSource]
    turn_context: str | None

    # --- Reply / voice ---
    messages: Annotated[list[BaseMessage], add_messages]
    reply_text: str | None
    # Set by memory_out_node; consumed by tts_node to address the persisted reply row.
    reply_id: str | None
    reply_audio: ReplyAudio | None

    # --- Bookkeeping ---
    routing_metadata: dict[str, Any]
    inbound_envelope: dict[str, Any]
