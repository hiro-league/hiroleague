"""Tests for ``UserMessageMirrorHook`` and ``EnvelopeFactory.user_message_mirror``.

The hook closes the in-process-producer gap: admin / CLI / agent ``message_send``
calls bypass the gateway broker, so without this hook, sibling devices would
never see the row live and would only catch up on the next explicit
``messages.history`` trigger. The factory builder is the canonical envelope
shape the hook emits — broadcast (no ``recipient_id``), same ``routing.id`` as
the inbound message for cross-tier idempotency.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

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
from hirocli.runtime.post_adapt_hooks import UserMessageMirrorHook


def _stub_ctx() -> SimpleNamespace:
    """Minimal stub matching the surface ``comm_peer_label`` touches.

    ``UserMessageMirrorHook.run`` only reads ``ctx.device_names.resolve``; we
    return the device id verbatim so log assertions remain straightforward.
    """
    device_names = SimpleNamespace(resolve=lambda device_id: device_id or "?")
    return SimpleNamespace(device_names=device_names)


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


# ---------------------------------------------------------------------------
# EnvelopeFactory.user_message_mirror
# ---------------------------------------------------------------------------


def test_user_message_mirror_preserves_id_for_idempotent_upsert() -> None:
    inbound = _inbound_text(msg_id="abc-123")

    mirror = EnvelopeFactory.user_message_mirror(inbound)

    # Same routing.id is the cross-tier dedup key: live broadcast and history
    # catch-up both upsert on this id, so a device that sees both never shows
    # a duplicate row.
    assert mirror.routing.id == "abc-123"


def test_user_message_mirror_is_broadcast_envelope() -> None:
    inbound = _inbound_text(sender_id="admin")

    mirror = EnvelopeFactory.user_message_mirror(inbound)

    assert mirror.message_type == MESSAGE_TYPE_MESSAGE
    assert mirror.routing.direction == "outbound"
    # Critical: no recipient_id ⇒ channel plugin omits target_device_id ⇒
    # gateway broadcasts to every paired device (relay.py: target_id is None
    # ⇒ broadcast branch).
    assert mirror.routing.recipient_id is None


def test_user_message_mirror_keeps_original_sender_id() -> None:
    """Originating identity travels with the mirror.

    The gateway's ``did != sender_id`` filter on the broadcast branch (see
    ``relay.py``) excludes the originating device automatically when it's a
    real device. For synthetic admin sends the sentinel ``admin`` is preserved
    so device-side filters / logs can tell admin/CLI traffic apart.
    """
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
    # text_preview lets log_scope show the user's words on the outbound mirror line.
    assert METADATA_LOG_TEXT_PREVIEW in mirror.routing.metadata


def test_user_message_mirror_does_not_mutate_origin() -> None:
    inbound = _inbound_text()
    snapshot_metadata = dict(inbound.routing.metadata)
    snapshot_content_count = len(inbound.content)

    EnvelopeFactory.user_message_mirror(inbound)

    assert inbound.routing.metadata == snapshot_metadata
    assert len(inbound.content) == snapshot_content_count


# ---------------------------------------------------------------------------
# UserMessageMirrorHook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hook_emits_one_broadcast_for_inbound_message() -> None:
    emitted: list[UnifiedMessage] = []

    async def emit(msg: UnifiedMessage) -> None:
        emitted.append(msg)

    hook = UserMessageMirrorHook(_stub_ctx())
    inbound = _inbound_text()

    await hook.run(inbound, emit)

    assert len(emitted) == 1
    out = emitted[0]
    assert out.routing.id == inbound.routing.id
    assert out.routing.direction == "outbound"
    assert out.routing.recipient_id is None


@pytest.mark.asyncio
async def test_hook_skips_outbound_messages() -> None:
    """Defensive guard: never re-mirror an already-outbound envelope.

    Post-adapt hooks today only see inbound messages, but the guard prevents a
    future re-entry from looping the mirror back through itself.
    """
    emitted: list[UnifiedMessage] = []

    async def emit(msg: UnifiedMessage) -> None:
        emitted.append(msg)

    hook = UserMessageMirrorHook(_stub_ctx())
    outbound = UnifiedMessage(
        routing=MessageRouting(
            id="server-msg-1",
            channel="devices",
            direction="outbound",
            sender_id="server",
            metadata={},
        ),
        content=[ContentItem(content_type=CONTENT_TYPE_TEXT, body="reply")],
    )

    await hook.run(outbound, emit)

    assert emitted == []


@pytest.mark.asyncio
async def test_hook_supports_admin_synthetic_sender() -> None:
    """The ``message_send`` tool stamps ``sender_id='admin'`` — the same hook path must work."""
    emitted: list[UnifiedMessage] = []

    async def emit(msg: UnifiedMessage) -> None:
        emitted.append(msg)

    hook = UserMessageMirrorHook(_stub_ctx())
    inbound = _inbound_text(sender_id="admin", msg_id="admin-uuid-9")

    await hook.run(inbound, emit)

    assert len(emitted) == 1
    assert emitted[0].routing.sender_id == "admin"
    assert emitted[0].routing.id == "admin-uuid-9"
    assert emitted[0].routing.recipient_id is None
