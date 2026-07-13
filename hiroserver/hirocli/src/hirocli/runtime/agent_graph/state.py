"""GraphState — per-turn state for the agent graph."""

from __future__ import annotations

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


def append_or_reset(left: list[Any] | None, right: list[Any] | None) -> list[Any]:
    """Reducer for per-turn fan-out scratch that must merge across parallel ``Send`` branches
    *within* a turn but reset *between* turns.

    Plain ``operator.add`` accumulates forever once the durable per-``thread_id`` checkpointer
    persists the channel: stale STT transcripts / vision descriptions from earlier turns then
    leak into every later turn's ``user_text`` (``gather_node`` re-joins them). A ``None`` update
    clears the channel — the turn's entry node (``ingest_node``) emits ``None`` to drop the prior
    turn's checkpointed scratch before this turn's STT / vision branches append their results.
    """
    if right is None:
        return []
    return (left or []) + list(right)


class GraphState(TypedDict, total=False):
    """Single state schema for the chat agent graph.

    Invariants (LangGraph channel semantics — keep this schema **flat**):

    1. **Checkpoint surface = ``messages`` only.** Every other field is per-turn scratch,
       overwritten each turn; its cross-turn value is undefined. The reducer-merged fan-out
       fields hold this only because ``ingest_node`` resets them each turn (see #4) — plain
       ``operator.add`` would let the durable checkpointer accumulate them across turns.
    2. **Reducer fields (``messages``, ``transcripts``, ``visions``, ``errors``) must stay
       top-level** — LangGraph keys reducers on channels; nesting them breaks parallel
       ``Send`` merges (default dict-overwrite loses data or raises ``InvalidUpdateError``).
    4. **Fan-out scratch resets each turn.** ``transcripts`` / ``visions`` / ``errors`` use
       ``append_or_reset`` (merge parallel branches, but a ``None`` clears); ``ingest_node``
       emits ``None`` at turn start so a durable checkpoint never carries them forward.
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
    # append_or_reset (not operator.add): merge parallel Send branches within a turn but
    # reset between turns. operator.add + the durable checkpointer accumulated these across
    # turns, leaking stale transcripts/visions into later user_text (ingest_node resets them).
    transcripts: Annotated[list[Transcript], append_or_reset]
    visions: Annotated[list[Vision], append_or_reset]
    errors: Annotated[list[NodeError], append_or_reset]

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
