"""``files.get`` emits ack JSON response, ``MESSAGE_TYPE_STREAM`` chunks, then terminal JSON."""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest
from hiro_channel_sdk.constants import CONTENT_TYPE_JSON, MESSAGE_TYPE_RESPONSE, MESSAGE_TYPE_STREAM
from hiro_channel_sdk.models import ContentItem, MessageRouting, UnifiedMessage

from hirocli.domain.blob_store import blob_id_for_file
from hirocli.domain.character import resolve_character_photo_file_for_http, seed_default_characters
from hirocli.runtime.request_handler import RequestContext
from hirocli.runtime.request_methods import handle_files_get


@pytest.mark.asyncio
async def test_files_get_emits_ack_stream_terminal(tmp_path_factory: pytest.TempPathFactory) -> None:
    tmp_path = tmp_path_factory.mktemp("ws")
    seed_default_characters(tmp_path)
    path, _mt = resolve_character_photo_file_for_http(tmp_path, "hiro")
    bid = blob_id_for_file(path)

    out: list[UnifiedMessage] = []

    async def emit(msg: UnifiedMessage) -> None:
        out.append(msg)

    srv = SimpleNamespace(workspace_path=tmp_path, workspace_name="default")
    req = UnifiedMessage(
        message_type="request",
        request_id="rid-1",
        routing=MessageRouting(
            id="r1",
            channel="devices",
            direction="inbound",
            sender_id="device-uuid",
        ),
        content=[
            ContentItem(
                content_type=CONTENT_TYPE_JSON,
                body=json.dumps({"method": "files.get", "params": {"blob_id": bid}}),
            )
        ],
    )
    rctx = RequestContext(srv, req, emit_outbound=emit)
    await handle_files_get({"blob_id": bid}, rctx)

    assert len(out) >= 3
    ack = out[0]
    assert ack.message_type == MESSAGE_TYPE_RESPONSE
    ack_body = json.loads(ack.content[0].body)
    assert ack_body["status"] == "ok"
    assert ack_body["data"]["chunk_count"] >= 1

    stream_msgs = [m for m in out if m.message_type == MESSAGE_TYPE_STREAM]
    assert len(stream_msgs) == ack_body["data"]["chunk_count"]
    assembled = b""
    for i, sm in enumerate(stream_msgs):
        assert sm.request_id == "rid-1"
        item = sm.content[0]
        assert item.metadata["seq"] == i
        assert item.metadata["blob_id"] == bid
        # Spec §5.4: only the last stream frame carries final=True.
        assert item.metadata["final"] is (i == len(stream_msgs) - 1)
        assembled += base64.b64decode(item.body)
    assert assembled == path.read_bytes()

    term = out[-1]
    assert term.message_type == MESSAGE_TYPE_RESPONSE
    term_body = json.loads(term.content[0].body)
    assert term_body["data"]["blob_id"] == bid
    assert term_body["data"]["size"] == len(assembled)
