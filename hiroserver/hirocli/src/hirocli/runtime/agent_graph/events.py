"""Graph events — explicit domain events emitted by nodes via ``StreamWriter``.

Subscribers (CommManager-side) react to these to produce wire envelopes
(``message.received``, ``message.transcribed``, text reply, ``message.voiced``)
and to perform persistence + user-message-mirror side effects.

The event name is the routing key; the payload is a small dict describing the
hop. Keep payloads small and reference-only — never embed audio bytes here.
"""

from __future__ import annotations

from typing import Any, TypedDict

# ---------------------------------------------------------------------------
# Event names
# ---------------------------------------------------------------------------

GRAPH_INGEST_COMPLETED = "graph.ingest.completed"
GRAPH_STT_COMPLETED = "graph.stt.completed"
GRAPH_VISION_COMPLETED = "graph.vision.completed"
GRAPH_REPLY_COMPLETED = "graph.reply.completed"
GRAPH_TTS_COMPLETED = "graph.tts.completed"
GRAPH_ERROR = "graph.error"


# ---------------------------------------------------------------------------
# Payloads (TypedDicts make the contract obvious to subscribers)
# ---------------------------------------------------------------------------


class IngestCompletedPayload(TypedDict):
    inbound_id: str
    chat_channel_id: int
    audio_count: int
    image_count: int
    text_count: int


class SttCompletedPayload(TypedDict):
    inbound_id: str
    chat_channel_id: int
    item_index: int
    transcript: str


class VisionCompletedPayload(TypedDict):
    inbound_id: str
    chat_channel_id: int
    item_index: int
    description: str


class ReplyCompletedPayload(TypedDict):
    inbound_id: str
    chat_channel_id: int
    thread_id: str
    reply_text: str
    reply_id: str
    request_voice_reply: bool


class TtsCompletedPayload(TypedDict):
    inbound_id: str
    chat_channel_id: int
    reply_id: str
    blob_id: str
    media_type: str
    size: int
    duration_ms: int | None
    audio_b64: str


class ErrorPayload(TypedDict):
    inbound_id: str
    node: str
    error: str


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_event(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap a payload with the routing-key event name for the custom stream."""
    return {"event": name, "payload": payload}
