"""EnvelopeFactory — central place to build server-originated UnifiedMessages.

Removes hand-rolled ``MessageRouting(direction="outbound", sender_id="server", …)``
boilerplate from every site that emits a reply, ack, or event. All envelopes
preserve the originating message's channel + metadata so the channel plugin
can route them back to the right device/conversation.
"""

from __future__ import annotations

import json
from typing import Any

from hiro_channel_sdk.constants import (
    CONTENT_TYPE_JSON,
    EVENT_TYPE_MESSAGE_RECEIVED,
    EVENT_TYPE_RESOURCE_CHANGED,
    EVENT_TYPE_MESSAGE_TRANSCRIBED,
    MESSAGE_TYPE_EVENT,
    MESSAGE_TYPE_RESPONSE,
)
from hiro_channel_sdk.models import (
    ContentItem,
    EventPayload,
    MessageRouting,
    UnifiedMessage,
)


_SERVER_SENDER_ID = "server"


def _outbound_routing(origin: UnifiedMessage) -> MessageRouting:
    """Build outbound routing that mirrors an inbound message back to its sender."""
    return MessageRouting(
        channel=origin.routing.channel,
        direction="outbound",
        sender_id=_SERVER_SENDER_ID,
        recipient_id=origin.routing.sender_id,
        metadata=origin.routing.metadata,
    )


def _direct_outbound_routing(
    *,
    channel: str,
    recipient_id: str,
    metadata: dict[str, Any] | None = None,
) -> MessageRouting:
    """Build outbound routing when there is no originating inbound message."""
    return MessageRouting(
        channel=channel,
        direction="outbound",
        sender_id=_SERVER_SENDER_ID,
        recipient_id=recipient_id,
        metadata=dict(metadata or {}),
    )


class EnvelopeFactory:
    """Builders for the server-originated UnifiedMessage shapes used by the runtime."""

    @staticmethod
    def ack_event(origin: UnifiedMessage) -> UnifiedMessage:
        """A ``message.received`` event acknowledging an inbound ``message``."""
        return UnifiedMessage(
            message_type=MESSAGE_TYPE_EVENT,
            routing=_outbound_routing(origin),
            event=EventPayload(
                type=EVENT_TYPE_MESSAGE_RECEIVED,
                ref_id=origin.routing.id,
            ),
        )

    @staticmethod
    def transcript_event(origin: UnifiedMessage, transcript: str) -> UnifiedMessage:
        """A ``message.transcribed`` event carrying the audio transcript text."""
        return UnifiedMessage(
            message_type=MESSAGE_TYPE_EVENT,
            routing=_outbound_routing(origin),
            event=EventPayload(
                type=EVENT_TYPE_MESSAGE_TRANSCRIBED,
                ref_id=origin.routing.id,
                data={"transcript": transcript},
            ),
        )

    @staticmethod
    def resource_changed_event(
        *,
        channel: str,
        recipient_id: str,
        data: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> UnifiedMessage:
        """A ``resource.changed`` event hint — carries ``resource``, ``reason``, and Tier-2 ``resource_sync_version``."""
        return UnifiedMessage(
            message_type=MESSAGE_TYPE_EVENT,
            routing=_direct_outbound_routing(
                channel=channel,
                recipient_id=recipient_id,
                metadata=metadata,
            ),
            event=EventPayload(
                type=EVENT_TYPE_RESOURCE_CHANGED,
                data=dict(data),
            ),
        )

    @staticmethod
    def response(
        request: UnifiedMessage,
        *,
        status: str,
        payload: dict[str, Any],
    ) -> UnifiedMessage:
        """A ``response`` envelope for a prior ``request``.

        ``status`` is ``"ok"`` or ``"error"``. ``payload`` becomes ``data`` on success
        and ``error`` on failure.
        """
        if status == "ok":
            body: dict[str, Any] = {"status": "ok", "data": payload}
        else:
            body = {"status": "error", "error": payload}

        return UnifiedMessage(
            message_type=MESSAGE_TYPE_RESPONSE,
            request_id=request.request_id,
            routing=_outbound_routing(request),
            content=[ContentItem(content_type=CONTENT_TYPE_JSON, body=json.dumps(body))],
        )

    @staticmethod
    def routing_error_response(origin: UnifiedMessage, reason: str) -> UnifiedMessage:
        """A response describing why the inbound message could not be routed.

        Used when ``message_type`` is unknown — there is no real ``request_id`` to
        correlate against, so we fall back to the routing id.
        """
        body = json.dumps({
            "status": "error",
            "error": {"code": "routing_error", "message": reason},
        })
        return UnifiedMessage(
            message_type=MESSAGE_TYPE_RESPONSE,
            request_id=origin.request_id or origin.routing.id,
            routing=_outbound_routing(origin),
            content=[ContentItem(content_type=CONTENT_TYPE_JSON, body=body)],
        )
