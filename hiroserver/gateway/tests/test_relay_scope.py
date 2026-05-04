"""Tests for gateway relay log-scope derivation."""

from __future__ import annotations

import json

from hiro_channel_sdk.log_scope_fields import METADATA_LOG_RPC_METHOD, METADATA_LOG_REPLY_TO_MSG_ID

from hirogateway.relay import _relay_log_scope_fields


def _make_um_payload(**parts: object) -> dict[str, object]:
    base: dict[str, object] = {
        "version": "0.1",
        "message_type": "message",
        "routing": {
            "id": "r-id",
            "channel": "devices",
            "direction": "inbound",
            "sender_id": "dev-x",
            "recipient_id": "server",
        },
        "content": [{"content_type": "text", "body": "hi"}],
    }
    base.update(parts)
    return base


def test_relay_scope_inbound_user_message_matches_sdk():
    msg = {"payload": _make_um_payload()}
    dev, mid, meth = _relay_log_scope_fields(
        msg,
        is_from_server=False,
        sender_id="dev-x",
        target_id=None,
    )
    assert dev == "dev-x"
    assert mid == "r-id"
    assert meth is None


def test_relay_scope_outbound_response_reads_rpc_method_metadata():
    um = _make_um_payload()
    um["message_type"] = "response"
    um["request_id"] = "req-99"
    assert isinstance(um["routing"], dict)
    routing = dict(um["routing"])
    routing["direction"] = "outbound"
    routing["sender_id"] = "server"
    routing["recipient_id"] = "peer-dev"
    routing["metadata"] = {METADATA_LOG_RPC_METHOD: "channels.list"}
    um["routing"] = routing
    um["content"] = [
        {"content_type": "json", "body": json.dumps({"status": "ok", "data": {}})}
    ]
    msg = {"payload": um}
    dev, mid, meth = _relay_log_scope_fields(
        msg,
        is_from_server=True,
        sender_id="desktop-id",
        target_id="peer-dev",
    )
    assert dev == "peer-dev"
    assert meth == "channels.list"
    assert mid is None


def test_relay_scope_outbound_reply_uses_reply_to_metadata():
    um = _make_um_payload()
    um["routing"] = {
        "id": "reply-env",
        "channel": "devices",
        "direction": "outbound",
        "sender_id": "server",
        "recipient_id": "peer-dev",
        "metadata": {METADATA_LOG_REPLY_TO_MSG_ID: "original-msg"},
    }
    msg = {"payload": um}
    dev, mid, meth = _relay_log_scope_fields(
        msg,
        is_from_server=True,
        sender_id="desktop-id",
        target_id="peer-dev",
    )
    assert dev == "peer-dev"
    assert mid == "original-msg"


def test_relay_scope_fallback_when_payload_invalid():
    msg = {"payload": {"not": "a unified message"}}
    dev, mid, meth = _relay_log_scope_fields(
        msg,
        is_from_server=False,
        sender_id="solo-dev",
        target_id=None,
    )
    assert dev == "solo-dev"
    assert mid is None
    assert meth is None
