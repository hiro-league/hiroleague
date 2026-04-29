"""Shared Pydantic models — the lingua franca of the plugin system."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Self
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from .constants import (
    CONTENT_TYPE_JSON,
    JSONRPC_VERSION,
    MESSAGE_TYPE_EVENT,
    MESSAGE_TYPE_MESSAGE,
    MESSAGE_TYPE_REQUEST,
    MESSAGE_TYPE_RESPONSE,
    MESSAGE_TYPE_STREAM,
)


class MessageRouting(BaseModel):
    """Routing and identification envelope for a UnifiedMessage.

    Carries who sent the message, where it came from, and where it should go.
    ``direction`` is always from the perspective of the Hiro server:
      - "inbound"  — arriving FROM the third party (e.g., user sent a Telegram msg)
      - "outbound" — to be SENT TO the third party (e.g., send a Telegram reply)
    """

    id: str = Field(default_factory=lambda: uuid4().hex)
    channel: str
    direction: str  # "inbound" | "outbound"
    sender_id: str
    recipient_id: str | None = None
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventPayload(BaseModel):
    """Payload for a UnifiedMessage with message_type 'event'.

    Events are fire-and-forget signals sent from the server to a device (or
    vice versa) to notify about activities without producing a chat message.

    ``type`` is a dotted event name, e.g. ``"message.received"``.
    ``ref_id`` links the event to the entity it is about — typically the
    ``routing.id`` of the message that triggered the event.
    ``data`` carries event-specific values (e.g. a transcript string).
    """

    type: str
    ref_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class ContentItem(BaseModel):
    """A single piece of content within a UnifiedMessage.

    Multiple items can be present in one message, for example a text caption
    alongside several images and a PDF file.
    """

    content_type: str  # "text" | "image" | "audio" | "video" | "file" | "location" | …
    body: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class UnifiedMessage(BaseModel):
    """Canonical cross-channel message format v0.1.

    Structured as two distinct concerns:
      - ``routing``      — who/where/when: channel, direction, sender, recipient, timestamp
      - ``content``      — ordered list of content items (text, images, audio, files, …)
      - ``event``        — present only when message_type is "event"; carries event type,
                           ref_id linking to the triggering entity, and event data

    ``version`` allows future parsers to handle multiple schema generations.
    ``message_type`` identifies the communication intent:
      - ``"message"``  — content exchange (implemented); requires at least one ContentItem
      - ``"event"``    — fire-and-forget signal (implemented); requires EventPayload, content empty
      - ``"request"``  — expects a response; request_id required
      - ``"response"`` — answer to a request; request_id echoes the request's
      - ``"stream"``   — reserved — streaming chunks

    ``request_id`` is a protocol-level correlation ID set by the requester and echoed
    by the responder. None for "message" and "event" types.
    """

    version: Literal["0.1"] = "0.1"
    message_type: Literal["message", "event", "request", "response", "stream"] = (
        MESSAGE_TYPE_MESSAGE
    )
    request_id: str | None = None
    routing: MessageRouting
    content: list[ContentItem] = Field(default_factory=list)
    event: EventPayload | None = None

    @model_validator(mode="after")
    def _validate_message_type_constraints(self) -> Self:
        if self.message_type == MESSAGE_TYPE_MESSAGE:
            # Content exchange must carry at least one content item and no event payload.
            if len(self.content) < 1:
                raise ValueError(
                    "message_type 'message' requires at least one content item"
                )
            if self.event is not None:
                raise ValueError(
                    "message_type 'message' must not carry an event payload"
                )
        elif self.message_type == MESSAGE_TYPE_EVENT:
            # Events must carry an event payload; content must be empty.
            if self.event is None:
                raise ValueError(
                    "message_type 'event' requires an event payload"
                )
            if len(self.content) > 0:
                raise ValueError(
                    "message_type 'event' must not carry content items"
                )
        elif self.message_type in (MESSAGE_TYPE_REQUEST, MESSAGE_TYPE_RESPONSE):
            if not self.request_id:
                raise ValueError(
                    f"message_type '{self.message_type}' requires request_id"
                )
            if self.event is not None:
                raise ValueError(
                    f"message_type '{self.message_type}' must not carry an event payload"
                )
            if not any(item.content_type == CONTENT_TYPE_JSON for item in self.content):
                raise ValueError(
                    f"message_type '{self.message_type}' requires a json content item"
                )
        elif self.message_type == MESSAGE_TYPE_STREAM:
            pass
        return self


class RpcRequest(BaseModel):
    """JSON-RPC 2.0 request or notification (notification when id is None)."""

    jsonrpc: str = JSONRPC_VERSION
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    id: str | int | None = None


class RpcResponse(BaseModel):
    """JSON-RPC 2.0 response."""

    jsonrpc: str = JSONRPC_VERSION
    result: Any = None
    error: dict[str, Any] | None = None
    id: str | int | None = None


class ChannelInfo(BaseModel):
    """Self-description that a channel sends on registration."""

    name: str
    version: str = "0.1.0"
    description: str = ""
