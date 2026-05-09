"""Canonical ``log_scope`` fields derived from ``UnifiedMessage``.

Each process (hirocli, channel plugin, gateway) re-derives these from the wire
model — ``contextvars`` do not cross process boundaries. See
``docs/log-scoping-and-filtering.md`` §2.1.
"""

from __future__ import annotations

import json
from typing import Literal

from .constants import (
    CONTENT_TYPE_AUDIO,
    CONTENT_TYPE_JSON,
    CONTENT_TYPE_TEXT,
    MESSAGE_TYPE_EVENT,
    MESSAGE_TYPE_MESSAGE,
    MESSAGE_TYPE_REQUEST,
    MESSAGE_TYPE_RESPONSE,
    MESSAGE_TYPE_STREAM,
)
from .models import UnifiedMessage

# Routing.metadata keys — stamped by runtime envelopes so outbound logs filter correctly.
METADATA_LOG_REPLY_TO_MSG_ID = "hiro_reply_to_msg_id"
METADATA_LOG_RPC_METHOD = "hiro_rpc_method"
METADATA_LOG_TEXT_PREVIEW = "hiro_log_text_preview"
# ``traffic_class`` is a producer-stamped operational classification (one of TRAFFIC_CLASSES).
# Stamped on outbound envelopes by EnvelopeFactory / AgentManager because the same
# (direction, message_type, event.type) tuple can mean either a lifecycle ack or a free-standing
# broadcast — the producer is the only one who knows which.
METADATA_LOG_TRAFFIC_CLASS = "hiro_traffic_class"
METADATA_LOG_TRAFFIC_SUBCLASS = "hiro_traffic_subclass"


# Tier-1 operational classification — stable enum, used as a log column / filter chip.
TRAFFIC_CLASS_INBOUND_MESSAGE = "inbound.message"
TRAFFIC_CLASS_INBOUND_EVENT = "inbound.event"
TRAFFIC_CLASS_INBOUND_REQUEST = "inbound.request"
TRAFFIC_CLASS_OUTBOUND_RESPONSE = "outbound.response"
TRAFFIC_CLASS_OUTBOUND_LIFECYCLE = "outbound.lifecycle"
TRAFFIC_CLASS_OUTBOUND_BROADCAST = "outbound.broadcast"
TRAFFIC_CLASS_OUTBOUND_REPLY = "outbound.reply"
TRAFFIC_CLASS_STREAM_CHUNK = "stream.chunk"
TRAFFIC_CLASS_INFRA_EVENT = "infra.event"
TRAFFIC_CLASS_INFRA_TRANSPORT = "infra.transport"

TRAFFIC_CLASSES: tuple[str, ...] = (
    TRAFFIC_CLASS_INBOUND_MESSAGE,
    TRAFFIC_CLASS_INBOUND_EVENT,
    TRAFFIC_CLASS_INBOUND_REQUEST,
    TRAFFIC_CLASS_OUTBOUND_RESPONSE,
    TRAFFIC_CLASS_OUTBOUND_LIFECYCLE,
    TRAFFIC_CLASS_OUTBOUND_BROADCAST,
    TRAFFIC_CLASS_OUTBOUND_REPLY,
    TRAFFIC_CLASS_STREAM_CHUNK,
    TRAFFIC_CLASS_INFRA_EVENT,
    TRAFFIC_CLASS_INFRA_TRANSPORT,
)

_LOG_PREVIEW_MAX = 80


def _snippet_log_text_preview(raw: str, max_len: int = _LOG_PREVIEW_MAX) -> str:
    """Single-line snippet for CSV ``extras`` — same shape as communication ``content_hint``."""
    cleaned = raw.replace("\n", " ").replace("\r", " ")
    t = " ".join(cleaned.split())
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def message_text_preview_from_content(msg: UnifiedMessage) -> str | None:
    """Human-readable snippet from chat content: text bodies and audio transcripts only.

    Prefer the first non-empty ``text`` body, else the first ``audio`` item with ``metadata.description``.
    JSON-RPC and other ``json`` content items are excluded so request/response payloads stay out of UIs.
    """
    for item in msg.content:
        if item.content_type == CONTENT_TYPE_TEXT:
            body = (item.body or "").strip()
            if body:
                return _snippet_log_text_preview(body)
    transcript: str | None = None
    for item in msg.content:
        if item.content_type == CONTENT_TYPE_AUDIO and item.metadata:
            desc_raw = item.metadata.get("description")
            if isinstance(desc_raw, str) and desc_raw.strip():
                transcript = desc_raw.strip()
                break
    if transcript:
        return _snippet_log_text_preview(transcript)
    return None


def unified_message_text_preview(msg: UnifiedMessage) -> str | None:
    """Effective log preview: stamped routing metadata wins, else derive from bodies."""
    meta = msg.routing.metadata or {}
    stamped = meta.get(METADATA_LOG_TEXT_PREVIEW)
    if isinstance(stamped, str) and stamped.strip():
        return _snippet_log_text_preview(stamped)
    return message_text_preview_from_content(msg)


def _json_rpc_method_from_request(msg: UnifiedMessage) -> str | None:
    """Return JSON-RPC ``method`` from the first json content item (request only)."""
    if msg.message_type != MESSAGE_TYPE_REQUEST:
        return None
    for item in msg.content:
        if item.content_type == CONTENT_TYPE_JSON:
            try:
                body = json.loads(item.body)
            except (json.JSONDecodeError, AttributeError, TypeError):
                continue
            m = body.get("method")
            if isinstance(m, str) and m.strip():
                return m.strip()
    return None


def _classify_traffic(
    msg: UnifiedMessage,
    *,
    direction: Literal["inbound", "outbound"],
) -> tuple[str, str | None]:
    """Derive ``(traffic_class, traffic_subclass)`` for a UnifiedMessage.

    For outbound envelopes, prefers the producer-stamped ``METADATA_LOG_TRAFFIC_CLASS``
    when present (only the producer can distinguish lifecycle vs broadcast); falls back
    to a deterministic mapping otherwise.
    """
    meta = msg.routing.metadata or {}
    mt = msg.message_type
    event_type = msg.event.type if msg.event else None

    if direction == "inbound":
        if mt == MESSAGE_TYPE_MESSAGE:
            sub = ",".join(c.content_type for c in msg.content) or None
            return TRAFFIC_CLASS_INBOUND_MESSAGE, sub
        if mt == MESSAGE_TYPE_REQUEST:
            return TRAFFIC_CLASS_INBOUND_REQUEST, _json_rpc_method_from_request(msg)
        if mt == MESSAGE_TYPE_EVENT:
            return TRAFFIC_CLASS_INBOUND_EVENT, event_type
        if mt == MESSAGE_TYPE_STREAM:
            stamped = meta.get(METADATA_LOG_RPC_METHOD)
            sub = stamped.strip() if isinstance(stamped, str) and stamped.strip() else None
            return TRAFFIC_CLASS_STREAM_CHUNK, sub
        return TRAFFIC_CLASS_INBOUND_MESSAGE, str(mt)

    stamped_class = meta.get(METADATA_LOG_TRAFFIC_CLASS)
    stamped_sub = meta.get(METADATA_LOG_TRAFFIC_SUBCLASS)
    if isinstance(stamped_class, str) and stamped_class.strip():
        sub = stamped_sub.strip() if isinstance(stamped_sub, str) and stamped_sub.strip() else None
        return stamped_class.strip(), sub

    if mt == MESSAGE_TYPE_RESPONSE:
        m = meta.get(METADATA_LOG_RPC_METHOD)
        return TRAFFIC_CLASS_OUTBOUND_RESPONSE, (
            m.strip() if isinstance(m, str) and m.strip() else None
        )
    if mt == MESSAGE_TYPE_STREAM:
        m = meta.get(METADATA_LOG_RPC_METHOD)
        return TRAFFIC_CLASS_STREAM_CHUNK, (
            m.strip() if isinstance(m, str) and m.strip() else None
        )
    if mt == MESSAGE_TYPE_MESSAGE:
        sub = ",".join(c.content_type for c in msg.content) or None
        return TRAFFIC_CLASS_OUTBOUND_REPLY, sub
    if mt == MESSAGE_TYPE_EVENT:
        # Without a producer stamp we cannot tell lifecycle (tied to an inbound message)
        # from broadcast (free-standing). ``ref_id`` is a strong-but-imperfect proxy:
        # lifecycle events always carry one; ``resource.changed`` does not.
        if msg.event and msg.event.ref_id:
            return TRAFFIC_CLASS_OUTBOUND_LIFECYCLE, event_type
        return TRAFFIC_CLASS_OUTBOUND_BROADCAST, event_type
    return TRAFFIC_CLASS_OUTBOUND_RESPONSE, str(mt)


def unified_message_log_scope(
    msg: UnifiedMessage,
    *,
    direction: Literal["inbound", "outbound"],
) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None]:
    """Return ``(device_id, msg_id, method, text_preview, traffic_class, traffic_subclass)``
    for :func:`hiro_commons.log.log_scope`.

    * **device_id** — peer device UUID (inbound: sender; outbound: recipient).
    * **msg_id** — conversation correlation (**never** attached to JSON-RPC ``request``/``response``
      envelopes — those use ``request_id`` / ``routing.id`` for transport only). For chat
      ``message`` / ``event`` types: user message ``routing.id``, ``event.ref_id``, or
      ``METADATA_LOG_REPLY_TO_MSG_ID`` on agent replies / voiced audio.
    * **method** — JSON-RPC method name for request (inbound) or response (outbound),
      when available.
    * **text_preview** — short human snippet (message text or post-STT transcript) for logs UI / filters.
    * **traffic_class** — Tier-1 operational classification (one of ``TRAFFIC_CLASSES``).
    * **traffic_subclass** — Tier-2 detail: method name, content shape, or event type.
    """
    r = msg.routing
    meta = r.metadata or {}
    traffic_class, traffic_subclass = _classify_traffic(msg, direction=direction)

    if direction == "inbound":
        device_id = r.sender_id or None
        method = _json_rpc_method_from_request(msg)
        text_preview_in = unified_message_text_preview(msg)

        # JSON-RPC envelopes are not chat lifecycle traffic — routing.id must never double as msg_id,
        # and stray inbound metadata keys must not tag them as conversational (admin message filter UX).
        if msg.message_type in (MESSAGE_TYPE_REQUEST, MESSAGE_TYPE_RESPONSE):
            return device_id, None, method, text_preview_in, traffic_class, traffic_subclass

        if msg.message_type == MESSAGE_TYPE_STREAM:
            m_rpc = meta.get(METADATA_LOG_RPC_METHOD)
            if isinstance(m_rpc, str) and m_rpc.strip():
                method = m_rpc.strip()
            return device_id, None, method, text_preview_in, traffic_class, traffic_subclass

        msg_id: str | None = None
        if msg.message_type == MESSAGE_TYPE_MESSAGE:
            msg_id = r.id
        elif msg.message_type == MESSAGE_TYPE_EVENT and msg.event and msg.event.ref_id:
            msg_id = msg.event.ref_id

        return device_id, msg_id, method, text_preview_in, traffic_class, traffic_subclass

    device_id = (r.recipient_id or r.sender_id or "").strip() or None

    method: str | None = None
    if msg.message_type == MESSAGE_TYPE_RESPONSE:
        m = meta.get(METADATA_LOG_RPC_METHOD)
        if isinstance(m, str) and m.strip():
            method = m.strip()
    elif msg.message_type == MESSAGE_TYPE_STREAM:
        m = meta.get(METADATA_LOG_RPC_METHOD)
        if isinstance(m, str) and m.strip():
            method = m.strip()

    tp_out_rpc = unified_message_text_preview(msg)
    if msg.message_type in (MESSAGE_TYPE_REQUEST, MESSAGE_TYPE_RESPONSE, MESSAGE_TYPE_STREAM):
        return device_id, None, method, tp_out_rpc, traffic_class, traffic_subclass

    reply_corr = meta.get(METADATA_LOG_REPLY_TO_MSG_ID)
    msg_id_out: str | None = None
    if isinstance(reply_corr, str) and reply_corr.strip():
        msg_id_out = reply_corr.strip()
    elif msg.message_type == MESSAGE_TYPE_EVENT and msg.event and msg.event.ref_id:
        msg_id_out = msg.event.ref_id
    elif msg.message_type == MESSAGE_TYPE_MESSAGE:
        msg_id_out = r.id

    text_preview_out = tp_out_rpc
    return device_id, msg_id_out, method, text_preview_out, traffic_class, traffic_subclass


def log_preview_snippet(raw: str) -> str:
    """Normalize user-generated text into a CSV-safe ≤80-char log preview fragment."""
    return _snippet_log_text_preview(raw)


__all__ = [
    "METADATA_LOG_REPLY_TO_MSG_ID",
    "METADATA_LOG_RPC_METHOD",
    "METADATA_LOG_TEXT_PREVIEW",
    "METADATA_LOG_TRAFFIC_CLASS",
    "METADATA_LOG_TRAFFIC_SUBCLASS",
    "TRAFFIC_CLASSES",
    "TRAFFIC_CLASS_INBOUND_MESSAGE",
    "TRAFFIC_CLASS_INBOUND_EVENT",
    "TRAFFIC_CLASS_INBOUND_REQUEST",
    "TRAFFIC_CLASS_OUTBOUND_RESPONSE",
    "TRAFFIC_CLASS_OUTBOUND_LIFECYCLE",
    "TRAFFIC_CLASS_OUTBOUND_BROADCAST",
    "TRAFFIC_CLASS_OUTBOUND_REPLY",
    "TRAFFIC_CLASS_STREAM_CHUNK",
    "TRAFFIC_CLASS_INFRA_EVENT",
    "TRAFFIC_CLASS_INFRA_TRANSPORT",
    "log_preview_snippet",
    "message_text_preview_from_content",
    "unified_message_text_preview",
    "unified_message_log_scope",
]
