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
    CONTENT_TYPE_FILE,
    CONTENT_TYPE_JSON,
    EVENT_TYPE_MESSAGE_RECEIVED,
    EVENT_TYPE_RESOURCE_CHANGED,
    EVENT_TYPE_MESSAGE_TRANSCRIBED,
    MESSAGE_TYPE_EVENT,
    MESSAGE_TYPE_RESPONSE,
    MESSAGE_TYPE_STREAM,
)
from hiro_channel_sdk.log_scope_fields import (
    METADATA_LOG_RPC_METHOD,
    METADATA_LOG_TEXT_PREVIEW,
    log_preview_snippet,
    message_text_preview_from_content,
)
from hiro_channel_sdk.models import (
    ContentItem,
    EventPayload,
    MessageRouting,
    UnifiedMessage,
)


_SERVER_SENDER_ID = "server"


def _merge_rpc_method_into_metadata(origin: UnifiedMessage, base_meta: dict[str, Any]) -> dict[str, Any]:
    """Copy ``base_meta`` and set ``METADATA_LOG_RPC_METHOD`` from JSON-RPC body when present."""
    out = dict(base_meta)
    for item in origin.content:
        if item.content_type == CONTENT_TYPE_JSON:
            try:
                req_body = json.loads(item.body)
                meth = req_body.get("method")
                if isinstance(meth, str) and meth.strip():
                    out[METADATA_LOG_RPC_METHOD] = meth.strip()
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass
            break
    return out


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
        # Carry text / transcript preview on routing.metadata so outbound log_scope matches the user-visible message.
        _ack_meta = dict(origin.routing.metadata or {})
        _pv_ack = message_text_preview_from_content(origin)
        if _pv_ack:
            _ack_meta[METADATA_LOG_TEXT_PREVIEW] = _pv_ack

        return UnifiedMessage(
            message_type=MESSAGE_TYPE_EVENT,
            routing=MessageRouting(
                channel=origin.routing.channel,
                direction="outbound",
                sender_id=_SERVER_SENDER_ID,
                recipient_id=origin.routing.sender_id,
                metadata=_ack_meta,
            ),
            event=EventPayload(
                type=EVENT_TYPE_MESSAGE_RECEIVED,
                ref_id=origin.routing.id,
            ),
        )

    @staticmethod
    def transcript_event(origin: UnifiedMessage, transcript: str) -> UnifiedMessage:
        """A ``message.transcribed`` event carrying the audio transcript text.

        Broadcasts (no ``recipient_id``) because the transcript is shared
        conversation content — every paired device of the user should see it,
        not only the device that recorded the original audio.
        """
        _txn_meta = dict(origin.routing.metadata or {})
        _txn_meta[METADATA_LOG_TEXT_PREVIEW] = log_preview_snippet(transcript)

        return UnifiedMessage(
            message_type=MESSAGE_TYPE_EVENT,
            routing=MessageRouting(
                channel=origin.routing.channel,
                direction="outbound",
                sender_id=_SERVER_SENDER_ID,
                metadata=_txn_meta,
            ),
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

        # Stamp JSON-RPC method on routing metadata so outbound ``log_scope`` can filter
        # RPC responses (JSON-RPC response bodies do not repeat ``method``).
        req_meta = _merge_rpc_method_into_metadata(request, dict(request.routing.metadata or {}))

        return UnifiedMessage(
            message_type=MESSAGE_TYPE_RESPONSE,
            request_id=request.request_id,
            routing=MessageRouting(
                channel=request.routing.channel,
                direction="outbound",
                sender_id=_SERVER_SENDER_ID,
                recipient_id=request.routing.sender_id,
                metadata=req_meta,
            ),
            content=[ContentItem(content_type=CONTENT_TYPE_JSON, body=json.dumps(body))],
        )

    @staticmethod
    def stream_chunk(
        origin_request: UnifiedMessage,
        *,
        blob_id: str,
        seq: int,
        final: bool,
        body_b64: str,
    ) -> UnifiedMessage:
        """One base64 chunk for an active ``files.get`` / upload session (``MESSAGE_TYPE_STREAM``)."""
        req_meta = _merge_rpc_method_into_metadata(
            origin_request,
            dict(origin_request.routing.metadata or {}),
        )
        return UnifiedMessage(
            message_type=MESSAGE_TYPE_STREAM,
            request_id=origin_request.request_id,
            routing=MessageRouting(
                channel=origin_request.routing.channel,
                direction="outbound",
                sender_id=_SERVER_SENDER_ID,
                recipient_id=origin_request.routing.sender_id,
                metadata=req_meta,
            ),
            content=[
                ContentItem(
                    content_type=CONTENT_TYPE_FILE,
                    body=body_b64,
                    metadata={
                        "blob_id": blob_id,
                        "seq": seq,
                        "final": final,
                    },
                )
            ],
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
        req_meta = _merge_rpc_method_into_metadata(origin, dict(origin.routing.metadata or {}))
        return UnifiedMessage(
            message_type=MESSAGE_TYPE_RESPONSE,
            request_id=origin.request_id or origin.routing.id,
            routing=MessageRouting(
                channel=origin.routing.channel,
                direction="outbound",
                sender_id=_SERVER_SENDER_ID,
                recipient_id=origin.routing.sender_id,
                metadata=req_meta,
            ),
            content=[ContentItem(content_type=CONTENT_TYPE_JSON, body=body)],
        )
