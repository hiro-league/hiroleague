"""``Send`` sub-state must carry singular media items, not parent lists (P1c)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from hiro_channel_sdk.constants import CONTENT_TYPE_AUDIO
from hiro_channel_sdk.models import ContentItem, MessageRouting, UnifiedMessage

from hirocli.runtime.agent_graph.nodes.media import MediaNodes
from hirocli.runtime.agent_graph.state import GraphState
from hirocli.runtime.tests.graph_fakes import make_agent_services

_STT_SEND_KEYS = frozenset(
    {"audio_item", "inbound_id", "chat_channel_id", "character_id", "routing_metadata"}
)


def _two_audio_envelope() -> dict[str, Any]:
    msg = UnifiedMessage(
        routing=MessageRouting(channel="test", direction="inbound", sender_id="user-1"),
        content=[
            ContentItem(
                content_type=CONTENT_TYPE_AUDIO,
                body="audio-one",
                metadata={"mime_type": "audio/m4a", "duration_ms": 1000, "size": 9},
            ),
            ContentItem(
                content_type=CONTENT_TYPE_AUDIO,
                body="audio-two",
                metadata={"mime_type": "audio/m4a", "duration_ms": 2000, "size": 9},
            ),
        ],
    )
    return msg.model_dump(mode="json")


@pytest.mark.asyncio
async def test_two_audio_items_emit_isolated_send_payloads(tmp_path: Path) -> None:
    media = MediaNodes(make_agent_services(tmp_path))
    envelope = _two_audio_envelope()
    ingested = await media.ingest_node(
        {
            "inbound_id": "in-1",
            "chat_channel_id": 42,
            "character_id": "hiro",
            "routing_metadata": {"route": "test"},
            "inbound_envelope": envelope,
            "voice_input_allowed": True,
        },
        lambda _event: None,
    )
    state: GraphState = {
        "inbound_id": "in-1",
        "chat_channel_id": 42,
        "character_id": "hiro",
        "routing_metadata": {"route": "test"},
        "audio_items": ingested["audio_items"],
        "image_items": [],
    }
    sends = media.dispatch_media(state)
    assert isinstance(sends, list)
    stt_sends = [send for send in sends if send.node == "stt"]
    assert len(stt_sends) == 2

    bodies = []
    for send in stt_sends:
        assert set(send.arg.keys()) == _STT_SEND_KEYS
        assert "audio_items" not in send.arg
        item = send.arg["audio_item"]
        assert item["body"] in {"audio-one", "audio-two"}
        bodies.append(item["body"])
    assert bodies == ["audio-one", "audio-two"]


def test_polluted_send_payload_would_fail_isolation_check() -> None:
    """Negative guard: replicating ``audio_items`` on a Send payload must fail the key pin."""
    clean = {
        "audio_item": {"item_index": 0, "body": "x", "mime_type": "audio/m4a"},
        "inbound_id": "in-1",
        "chat_channel_id": 1,
        "character_id": "hiro",
        "routing_metadata": {},
    }
    polluted = {**clean, "audio_items": [clean["audio_item"]]}
    assert set(clean.keys()) == _STT_SEND_KEYS
    assert set(polluted.keys()) != _STT_SEND_KEYS
    assert "audio_items" in polluted
