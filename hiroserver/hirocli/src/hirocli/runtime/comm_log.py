"""Shared human-first logging helpers for the communication path.

Used by ``CommunicationManager``, ``ChannelManager``, ``AgentManager`` (and any
future runtime peer) so every log line about a UnifiedMessage carries the same
shape: direction arrow, peer label, kind summary, optional content hint,
followed by opaque ids.

This module exists to decouple the logging vocabulary from any one manager —
previously these helpers lived in ``communication_manager.py`` and were
imported across module boundaries by their underscore-prefixed names.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from hiro_channel_sdk.constants import (
    CONTENT_TYPE_AUDIO,
    CONTENT_TYPE_JSON,
    CONTENT_TYPE_TEXT,
    MESSAGE_TYPE_EVENT,
    MESSAGE_TYPE_MESSAGE,
    MESSAGE_TYPE_REQUEST,
    MESSAGE_TYPE_RESPONSE,
)
from hiro_channel_sdk.models import UnifiedMessage

if TYPE_CHECKING:
    from .server_context import ServerContext


# Direction arrows (server-centric: inbound = traffic ending up at the server).
LOG_IN = "⬇️"
LOG_OUT = "⬆️"

_TEXT_SNIPPET_MAX = 120


def _parse_req_resp_body(msg: UnifiedMessage) -> dict[str, Any]:
    """Parse the first JSON content item for request/response detail fields."""
    for item in msg.content:
        if item.content_type == CONTENT_TYPE_JSON:
            try:
                return json.loads(item.body)
            except (json.JSONDecodeError, AttributeError):
                pass
    return {}


def comm_kind(msg: UnifiedMessage) -> str:
    """Short type summary: message[text,audio], event:message.received, request:method, …"""
    mt = msg.message_type
    if mt == MESSAGE_TYPE_MESSAGE:
        if not msg.content:
            return "message[]"
        return f"message[{','.join(c.content_type for c in msg.content)}]"
    if mt == MESSAGE_TYPE_EVENT:
        et = msg.event.type if msg.event else "?"
        return f"event:{et}"
    if mt == MESSAGE_TYPE_REQUEST:
        method = _parse_req_resp_body(msg).get("method")
        return f"request:{method}" if method else "request"
    if mt == MESSAGE_TYPE_RESPONSE:
        status = _parse_req_resp_body(msg).get("status", "?")
        return f"response[{status}]"
    return str(mt)


def _snippet_text(body: str, max_len: int = _TEXT_SNIPPET_MAX) -> str:
    t = " ".join(body.split())
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _comm_content_hint(msg: UnifiedMessage) -> str | None:
    """Text snippet per item, or labels like audio/json/image for non-text bodies."""
    if msg.message_type != MESSAGE_TYPE_MESSAGE or not msg.content:
        return None
    parts: list[str] = []
    for item in msg.content:
        ct = item.content_type
        if ct == CONTENT_TYPE_TEXT:
            parts.append(_snippet_text(item.body) if item.body.strip() else "text:(empty)")
        elif ct == CONTENT_TYPE_AUDIO:
            parts.append("audio")
        elif ct == CONTENT_TYPE_JSON:
            parts.append(_snippet_text(item.body, 80) if item.body.strip() else "json:(empty)")
        else:
            parts.append(ct)
    return " | ".join(parts) if parts else None


def _req_resp_extras(msg: UnifiedMessage) -> dict[str, Any]:
    """Extract request/response-specific fields for log extras."""
    if msg.message_type not in (MESSAGE_TYPE_REQUEST, MESSAGE_TYPE_RESPONSE):
        return {}
    body = _parse_req_resp_body(msg)
    if not body:
        return {}
    out: dict[str, Any] = {}
    if msg.message_type == MESSAGE_TYPE_REQUEST:
        if "method" in body:
            out["method"] = body["method"]
        if body.get("params"):
            out["params"] = body["params"]
    else:
        if "status" in body:
            out["status"] = body["status"]
        if "error" in body:
            out["error"] = body["error"]
        if "data" in body:
            out["data"] = body["data"]
    return out


def comm_extras(msg: UnifiedMessage, **kwargs: Any) -> dict[str, Any]:
    """Build log extras: request/response details, then content_hint, then caller fields."""
    out: dict[str, Any] = {}
    rr = _req_resp_extras(msg)
    if rr:
        out.update(rr)
    hint = _comm_content_hint(msg)
    if hint:
        out["content_hint"] = hint
    out.update(kwargs)
    return out


def comm_peer_label(msg: UnifiedMessage, ctx: ServerContext) -> str:
    """Short peer label for logs: friendly name when known, else device_id."""
    if msg.routing.direction == "outbound":
        device_id = (msg.routing.recipient_id or msg.routing.sender_id or "").strip()
    else:
        device_id = (msg.routing.sender_id or "").strip()

    meta = msg.routing.metadata or {}
    dn = meta.get("device_name")
    if isinstance(dn, str) and dn.strip():
        s = dn.strip()
        # Legacy "Name (device_id)" from older servers — drop id when it matches this peer.
        if device_id and s.endswith(f" ({device_id})"):
            return s[: -len(f" ({device_id})")]
        return s

    return ctx.device_names.resolve(device_id)
