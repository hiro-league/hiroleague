"""A chat message's story through its first hops: the device's frame through the gateway's relay, then into the devices
plugin, each hop a timed step that the frame carries on to the next."""

from __future__ import annotations

import asyncio
import json

from hiro_channel_sdk.constants import AUTH_ROLE_DESKTOP
from hiro_commons import logging_foundation as foundation
from hiro_commons.logging_foundation import daily, story
from hiro_channel_devices.plugin import DevicesChannel

from hirogateway import relay

MESSAGE_ID = "6f1c2a3b-4d5e-4f60-8a71-92b3c4d5e6f7"  # as the device makes it
STORY_ID = MESSAGE_ID.replace("-", "")


class _Socket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)


def _device_frame() -> str:
    return json.dumps({"payload": {
        "version": "0.1", "message_type": "message",
        "routing": {"id": MESSAGE_ID, "channel": "devices", "direction": "inbound", "sender_id": "dev-x"},
        "content": [{"content_type": "text", "body": "hi Hiro"}],
    }})


def test_the_device_message_is_one_story_through_the_gateway_and_the_plugin(tmp_path, monkeypatch):
    monkeypatch.delenv(foundation.LEVELS_SETTING, raising=False)
    foundation.setup(tmp_path, name="gateway", service="gateway", console=False)
    desktop = _Socket()
    monkeypatch.setattr(relay, "_registry", {"plugin-desktop": desktop, "dev-x": _Socket()})
    monkeypatch.setattr(relay, "_device_roles", {"plugin-desktop": AUTH_ROLE_DESKTOP, "dev-x": "device"})

    asyncio.run(relay.relay_message("dev-x", _device_frame()))

    (forwarded,) = desktop.sent
    carried = json.loads(forwarded)["payload"]["routing"]["metadata"]["traceparent"]
    assert carried.split("-")[1] == STORY_ID  # the story is the message's own id

    plugin = DevicesChannel()
    received = []

    async def emit(msg):
        received.append((msg, story.current()))

    plugin._emit_callback = emit
    asyncio.run(plugin._handle_gateway_message(forwarded))
    (msg, now), = received
    assert now[0] == STORY_ID
    assert msg.routing.metadata["traceparent"] == f"00-{STORY_ID}-{now[1]}-01"  # on to the server

    foundation.flush()
    lines = [json.loads(t) for _d, p in daily.files(tmp_path, "gateway") for t in p.read_text(encoding="utf-8").splitlines()]
    steps = {ln["Attributes"]["step"]: ln for ln in lines if "step" in ln.get("Attributes", {})}
    relay_step, receive_step = steps["gateway.relay"], steps["devices.receive"]
    assert relay_step["TraceId"] == receive_step["TraceId"] == STORY_ID
    assert relay_step["SpanId"] == carried.split("-")[2]
    assert receive_step["Attributes"]["parent_step"] == relay_step["SpanId"]
    assert relay_step["Attributes"]["elapsed_ms"] >= 0 and relay_step["Body"].startswith("gateway.relay took")
    received_line = next(ln for ln in lines if ln["Body"].startswith("📥 Inbound message from gateway"))
    assert received_line["SpanId"] == receive_step["SpanId"]  # the hop's own lines carry its step
    foundation.close()
