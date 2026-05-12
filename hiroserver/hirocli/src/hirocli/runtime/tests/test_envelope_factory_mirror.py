"""Tests for ``EnvelopeFactory.user_message_mirror``.

The mirror envelope itself is unchanged after the agent-graph redesign; only
its emitter moved (post-adapt hook → ``GraphEventSubscriber``). These tests
guard the wire shape that downstream device handlers rely on.
"""

from __future__ import annotations

from hiro_channel_sdk.constants import (
    CONTENT_TYPE_AUDIO,
    CONTENT_TYPE_TEXT,
    MESSAGE_TYPE_MESSAGE,
)
from hiro_channel_sdk.log_scope_fields import (
    METADATA_LOG_TEXT_PREVIEW,
    METADATA_LOG_TRAFFIC_CLASS,
    METADATA_LOG_TRAFFIC_SUBCLASS,
    TRAFFIC_CLASS_OUTBOUND_BROADCAST,
)
from hiro_channel_sdk.models import ContentItem, MessageRouting, UnifiedMessage
from hirocli.runtime.envelope_factory import EnvelopeFactory


def _inbound_text(
    *,
    msg_id: str = "user-msg-1",
    sender_id: str = "device-aaa",
    body: str = "hello world",
    chat_channel_id: int = 7,
) -> UnifiedMessage:
    return UnifiedMessage(
        message_type=MESSAGE_TYPE_MESSAGE,
        routing=MessageRouting(
            id=msg_id,
            channel="devices",
            direction="inbound",
            sender_id=sender_id,
            metadata={"chat_channel_id": chat_channel_id},
        ),
        content=[ContentItem(content_type=CONTENT_TYPE_TEXT, body=body)],
    )


def test_user_message_mirror_preserves_id_for_idempotent_upsert() -> None:
    inbound = _inbound_text(msg_id="abc-123")
    mirror = EnvelopeFactory.user_message_mirror(inbound)
    assert mirror.routing.id == "abc-123"


def test_user_message_mirror_is_broadcast_envelope() -> None:
    inbound = _inbound_text(sender_id="admin")
    mirror = EnvelopeFactory.user_message_mirror(inbound)
    assert mirror.message_type == MESSAGE_TYPE_MESSAGE
    assert mirror.routing.direction == "outbound"
    assert mirror.routing.recipient_id is None


def test_user_message_mirror_keeps_original_sender_id() -> None:
    inbound = _inbound_text(sender_id="device-aaa")
    mirror = EnvelopeFactory.user_message_mirror(inbound)
    assert mirror.routing.sender_id == "device-aaa"


def test_user_message_mirror_preserves_timestamp_and_channel() -> None:
    inbound = _inbound_text()
    mirror = EnvelopeFactory.user_message_mirror(inbound)
    assert mirror.routing.channel == inbound.routing.channel
    assert mirror.routing.timestamp == inbound.routing.timestamp


def test_user_message_mirror_carries_full_content() -> None:
    inbound = UnifiedMessage(
        routing=MessageRouting(
            id="m1",
            channel="devices",
            direction="inbound",
            sender_id="admin",
            metadata={"chat_channel_id": 1},
        ),
        content=[
            ContentItem(content_type=CONTENT_TYPE_TEXT, body="caption"),
            ContentItem(
                content_type=CONTENT_TYPE_AUDIO,
                body="<base64-bytes>",
                metadata={"blob_id": "sha256:abc", "duration_ms": 1500},
            ),
        ],
    )
    mirror = EnvelopeFactory.user_message_mirror(inbound)
    assert len(mirror.content) == 2
    assert mirror.content[0].body == "caption"
    assert mirror.content[1].metadata["blob_id"] == "sha256:abc"


def test_user_message_mirror_stamps_traffic_class_for_logs() -> None:
    inbound = _inbound_text(body="hello")
    mirror = EnvelopeFactory.user_message_mirror(inbound)
    assert (
        mirror.routing.metadata[METADATA_LOG_TRAFFIC_CLASS]
        == TRAFFIC_CLASS_OUTBOUND_BROADCAST
    )
    assert (
        mirror.routing.metadata[METADATA_LOG_TRAFFIC_SUBCLASS] == "user_message_mirror"
    )
    assert METADATA_LOG_TEXT_PREVIEW in mirror.routing.metadata


def test_user_message_mirror_does_not_mutate_origin() -> None:
    inbound = _inbound_text()
    snapshot_metadata = dict(inbound.routing.metadata)
    snapshot_content_count = len(inbound.content)
    EnvelopeFactory.user_message_mirror(inbound)
    assert inbound.routing.metadata == snapshot_metadata
    assert len(inbound.content) == snapshot_content_count
