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


def unified_message_log_scope(
    msg: UnifiedMessage,
    *,
    direction: Literal["inbound", "outbound"],
) -> tuple[str | None, str | None, str | None, str | None]:
    """Return ``(device_id, msg_id, method, text_preview)`` for :func:`hiro_commons.log.log_scope`.

    * **device_id** — peer device UUID (inbound: sender; outbound: recipient).
    * **msg_id** — conversation correlation (**never** attached to JSON-RPC ``request``/``response``
      envelopes — those use ``request_id`` / ``routing.id`` for transport only). For chat
      ``message`` / ``event`` types: user message ``routing.id``, ``event.ref_id``, or
      ``METADATA_LOG_REPLY_TO_MSG_ID`` on agent replies / voiced audio.
    * **method** — JSON-RPC method name for request (inbound) or response (outbound),
      when available.
    * **text_preview** — short human snippet (message text or post-STT transcript) for logs UI / filters.
    """
    r = msg.routing
    meta = r.metadata or {}

    if direction == "inbound":
        device_id = r.sender_id or None
        method = _json_rpc_method_from_request(msg)
        text_preview_in = unified_message_text_preview(msg)

        # JSON-RPC envelopes are not chat lifecycle traffic — routing.id must never double as msg_id,
        # and stray inbound metadata keys must not tag them as conversational (admin message filter UX).
        if msg.message_type in (MESSAGE_TYPE_REQUEST, MESSAGE_TYPE_RESPONSE):
            return device_id, None, method, text_preview_in

        if msg.message_type == MESSAGE_TYPE_STREAM:
            m_rpc = meta.get(METADATA_LOG_RPC_METHOD)
            if isinstance(m_rpc, str) and m_rpc.strip():
                method = m_rpc.strip()
            return device_id, None, method, text_preview_in

        msg_id: str | None = None
        if msg.message_type == MESSAGE_TYPE_MESSAGE:
            msg_id = r.id
        elif msg.message_type == MESSAGE_TYPE_EVENT and msg.event and msg.event.ref_id:
            msg_id = msg.event.ref_id

        return device_id, msg_id, method, text_preview_in

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
        return device_id, None, method, tp_out_rpc

    reply_corr = meta.get(METADATA_LOG_REPLY_TO_MSG_ID)
    msg_id_out: str | None = None
    if isinstance(reply_corr, str) and reply_corr.strip():
        msg_id_out = reply_corr.strip()
    elif msg.message_type == MESSAGE_TYPE_EVENT and msg.event and msg.event.ref_id:
        msg_id_out = msg.event.ref_id
    elif msg.message_type == MESSAGE_TYPE_MESSAGE:
        msg_id_out = r.id

    text_preview_out = tp_out_rpc
    return device_id, msg_id_out, method, text_preview_out


def log_preview_snippet(raw: str) -> str:
    """Normalize user-generated text into a CSV-safe ≤80-char log preview fragment."""
    return _snippet_log_text_preview(raw)


__all__ = [
    "METADATA_LOG_REPLY_TO_MSG_ID",
    "METADATA_LOG_RPC_METHOD",
    "METADATA_LOG_TEXT_PREVIEW",
    "log_preview_snippet",
    "message_text_preview_from_content",
    "unified_message_text_preview",
    "unified_message_log_scope",
]
