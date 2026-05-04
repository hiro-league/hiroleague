"""Tests for :mod:`hiro_channel_sdk.log_scope_fields`."""

from __future__ import annotations

import json

from hiro_channel_sdk.constants import CONTENT_TYPE_JSON, MESSAGE_TYPE_EVENT, MESSAGE_TYPE_MESSAGE
from hiro_channel_sdk.constants import MESSAGE_TYPE_REQUEST, MESSAGE_TYPE_RESPONSE
from hiro_channel_sdk.log_scope_fields import (
    METADATA_LOG_REPLY_TO_MSG_ID,
    METADATA_LOG_RPC_METHOD,
    METADATA_LOG_TEXT_PREVIEW,
    unified_message_log_scope,
)
from hiro_channel_sdk.models import ContentItem, EventPayload, MessageRouting, UnifiedMessage


def _routing(**kwargs: object) -> MessageRouting:
    base: dict[str, object] = {
        "channel": "devices",
        "direction": "inbound",
        "sender_id": "sender-dev",
        "recipient_id": "server",
        "id": "route-msg-1",
    }
    base.update(kwargs)
    return MessageRouting.model_validate(base)


def test_inbound_user_message_scope():
    msg = UnifiedMessage(
        message_type=MESSAGE_TYPE_MESSAGE,
        routing=_routing(sender_id="d1", id="mid-99"),
        content=[ContentItem(content_type="text", body="hello world transcript")],
    )
    dev, mid, meth, preview = unified_message_log_scope(msg, direction="inbound")
    assert dev == "d1"
    assert mid == "mid-99"
    assert meth is None
    assert preview == "hello world transcript"


def test_inbound_event_uses_ref_id_not_routing_id():
    msg = UnifiedMessage(
        message_type=MESSAGE_TYPE_EVENT,
        routing=_routing(sender_id="d2", id="evt-route-self"),
        event=EventPayload(type="message.received", ref_id="original-msg"),
    )
    dev, mid, meth, preview = unified_message_log_scope(msg, direction="inbound")
    assert dev == "d2"
    assert mid == "original-msg"
    assert meth is None
    assert preview is None


def test_inbound_json_rpc_request_extracts_method():
    msg = UnifiedMessage(
        message_type=MESSAGE_TYPE_REQUEST,
        request_id="req-1",
        routing=_routing(sender_id="d3"),
        content=[
            ContentItem(
                content_type=CONTENT_TYPE_JSON,
                body=json.dumps({"jsonrpc": "2.0", "method": "channels.list", "id": 1}),
            )
        ],
    )
    dev, mid, meth, preview = unified_message_log_scope(msg, direction="inbound")
    assert dev == "d3"
    assert mid is None
    assert meth == "channels.list"
    assert preview is None


def test_outbound_response_reads_rpc_method_from_metadata():
    msg = UnifiedMessage(
        message_type=MESSAGE_TYPE_RESPONSE,
        request_id="r1",
        routing=_routing(
            direction="outbound",
            sender_id="server",
            recipient_id="target-dev",
            metadata={METADATA_LOG_RPC_METHOD: "policy.get"},
        ),
        content=[
            ContentItem(content_type=CONTENT_TYPE_JSON, body=json.dumps({"status": "ok", "data": {}}))
        ],
    )
    dev, mid, meth, preview = unified_message_log_scope(msg, direction="outbound")
    assert dev == "target-dev"
    assert meth == "policy.get"
    assert mid is None
    assert preview is None


def test_outbound_agent_reply_prefers_reply_to_metadata():
    msg = UnifiedMessage(
        message_type=MESSAGE_TYPE_MESSAGE,
        routing=_routing(
            direction="outbound",
            sender_id="server",
            recipient_id="peer",
            id="reply-envelope-id",
            metadata={METADATA_LOG_REPLY_TO_MSG_ID: "user-original"},
        ),
        content=[ContentItem(content_type="text", body="reply text")],
    )
    dev, mid, meth, preview = unified_message_log_scope(msg, direction="outbound")
    assert dev == "peer"
    assert mid == "user-original"
    assert meth is None
    assert preview == "reply text"


def test_outbound_agent_reply_uses_stamped_user_anchor_over_body():
    """Runtime stamps ``METADATA_LOG_TEXT_PREVIEW`` on replies so logs anchor on the user's words."""
    msg = UnifiedMessage(
        message_type=MESSAGE_TYPE_MESSAGE,
        routing=_routing(
            direction="outbound",
            sender_id="server",
            recipient_id="peer",
            id="reply-envelope-id",
            metadata={
                METADATA_LOG_REPLY_TO_MSG_ID: "user-original",
                METADATA_LOG_TEXT_PREVIEW: "user question here",
            },
        ),
        content=[ContentItem(content_type="text", body="long agent reply text")],
    )
    _, mid, _, preview = unified_message_log_scope(msg, direction="outbound")
    assert mid == "user-original"
    assert preview == "user question here"


def test_inbound_request_ignores_spoofed_reply_correlation():
    msg = UnifiedMessage(
        message_type=MESSAGE_TYPE_REQUEST,
        request_id="req-1",
        routing=_routing(
            sender_id="d3",
            metadata={METADATA_LOG_REPLY_TO_MSG_ID: "should-not-attach"},
        ),
        content=[
            ContentItem(
                content_type=CONTENT_TYPE_JSON,
                body=json.dumps({"jsonrpc": "2.0", "method": "channels.list", "id": 1}),
            )
        ],
    )
    _, mid, _, _ = unified_message_log_scope(msg, direction="inbound")
    assert mid is None


def test_outbound_response_never_uses_reply_correlation_metadata():
    msg = UnifiedMessage(
        message_type=MESSAGE_TYPE_RESPONSE,
        request_id="r1",
        routing=_routing(
            direction="outbound",
            sender_id="server",
            recipient_id="target-dev",
            metadata={
                METADATA_LOG_RPC_METHOD: "channels.list",
                METADATA_LOG_REPLY_TO_MSG_ID: "should-not-attach",
            },
        ),
        content=[
            ContentItem(content_type=CONTENT_TYPE_JSON, body=json.dumps({"status": "ok", "data": {}}))
        ],
    )
    dev, mid, meth, preview = unified_message_log_scope(msg, direction="outbound")
    assert dev == "target-dev"
    assert mid is None
    assert meth == "channels.list"
    assert preview is None


def test_outbound_event_falls_back_to_ref_id():
    msg = UnifiedMessage(
        message_type=MESSAGE_TYPE_EVENT,
        request_id="irrelevant",
        routing=_routing(direction="outbound", sender_id="server", recipient_id="dev-z"),
        event=EventPayload(type="message.voiced", ref_id="correlated"),
    )
    dev, mid, meth, preview = unified_message_log_scope(msg, direction="outbound")
    assert dev == "dev-z"
    assert mid == "correlated"
    assert preview is None


def test_outbound_stamped_metadata_text_preview_used_for_correlated_events():
    msg = UnifiedMessage(
        message_type=MESSAGE_TYPE_EVENT,
        routing=_routing(
            direction="outbound",
            sender_id="server",
            recipient_id="peer",
            metadata={
                METADATA_LOG_REPLY_TO_MSG_ID: "user-original",
                METADATA_LOG_TEXT_PREVIEW: "STT snippet for logs",
            },
        ),
        event=EventPayload(type="message.transcribed", ref_id="user-original", data={"transcript": "x"}),
    )
    _, mid, _, preview = unified_message_log_scope(msg, direction="outbound")
    assert mid == "user-original"
    assert preview == "STT snippet for logs"
