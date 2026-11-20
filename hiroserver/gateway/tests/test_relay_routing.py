"""Where the relay sends a frame: a device's goes to HiroServer only; HiroServer's to one device or all of them. And
HiroServer's list of paired devices cuts off a device removed in the admin."""

from __future__ import annotations

import asyncio
import json

import pytest
from hiro_channel_sdk.constants import AUTH_ROLE_DESKTOP, AUTH_ROLE_DEVICE

from hirogateway import relay


class _Socket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed: tuple[int, str] | None = None

    async def send(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = (code, reason)


def _frame(target: str | None = None) -> str:
    frame: dict = {"payload": {
        "version": "0.1", "message_type": "message",
        "routing": {"id": "6f1c2a3b-4d5e-4f60-8a71-92b3c4d5e6f7", "channel": "devices", "direction": "inbound",
                    "sender_id": "x"},
        "content": [{"content_type": "text", "body": "hi Hiro"}],
    }}
    if target:
        frame["target_device_id"] = target
    return json.dumps(frame)


@pytest.fixture
def sockets(monkeypatch):
    s = {"server": _Socket(), "phone-a": _Socket(), "phone-b": _Socket()}
    monkeypatch.setattr(relay, "_registry", dict(s))
    monkeypatch.setattr(relay, "_device_roles", {"server": AUTH_ROLE_DESKTOP, "phone-a": AUTH_ROLE_DEVICE,
                                                 "phone-b": AUTH_ROLE_DEVICE})
    monkeypatch.setattr(relay, "_allowed_devices", None)
    return s


def test_a_device_frame_reaches_the_server_and_no_other_device(sockets):
    asyncio.run(relay.relay_message("phone-a", _frame()))
    assert len(sockets["server"].sent) == 1 and sockets["server"].sent[0]["sender_device_id"] == "phone-a"
    assert sockets["phone-b"].sent == []  # before, a broadcast: every other family phone got it too


def test_a_device_cannot_aim_a_frame_at_another_device(sockets):
    asyncio.run(relay.relay_message("phone-a", _frame(target="phone-b")))
    assert sockets["phone-b"].sent == [] and len(sockets["server"].sent) == 1


def test_the_server_reaches_one_device_or_all(sockets):
    asyncio.run(relay.relay_message("server", _frame(target="phone-b")))
    assert sockets["phone-a"].sent == [] and len(sockets["phone-b"].sent) == 1
    asyncio.run(relay.relay_message("server", _frame()))
    assert len(sockets["phone-a"].sent) == 1 and len(sockets["phone-b"].sent) == 2


def test_a_device_the_server_no_longer_lists_is_cut_off(sockets):
    asyncio.run(relay._set_allowed_devices({"type": "allowed_devices", "device_ids": ["phone-a"]}))
    assert relay._allowed_devices == {"phone-a"}
    assert sockets["phone-b"].closed is not None and sockets["phone-a"].closed is None
    assert sockets["server"].closed is None  # the server is never on the list, and never cut off


def test_a_list_that_is_not_a_list_of_ids_changes_nothing(sockets):
    asyncio.run(relay._set_allowed_devices({"type": "allowed_devices", "device_ids": "phone-a"}))
    assert relay._allowed_devices is None and sockets["phone-b"].closed is None
