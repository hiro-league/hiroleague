"""Who the WhatsApp channel lets through (Permissions phase 3): only the numbers the core hands it, the people who may
talk to Hiro, and never a group's message. neonize is faked (conftest.py)."""

from __future__ import annotations

import asyncio
import importlib
import sys
from typing import Any

import pytest


@pytest.fixture
def channel(monkeypatch: pytest.MonkeyPatch, stub_neonize: None):
    for name in ("hiro_channel_whatsapp.wa_client", "hiro_channel_whatsapp.plugin"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    module = importlib.import_module("hiro_channel_whatsapp.plugin")
    plugin = module.WhatsAppChannel()
    plugin.emitted = []

    async def emit(message: Any) -> None:
        plugin.emitted.append(message)

    plugin.emit = emit
    yield plugin
    for name in ("hiro_channel_whatsapp.wa_client", "hiro_channel_whatsapp.plugin"):
        sys.modules.pop(name, None)


def _inbound(number: str, *, group: bool = False) -> dict[str, Any]:
    return {"sender_pn": number, "sender_jid": "1234567890@lid", "is_group": group, "text": "hi", "msg_id": "m1"}


def test_only_the_cores_numbers_pass_and_the_owner_number_is_read_no_more(channel) -> None:
    asyncio.run(channel.on_configure({"owner_number": "201000000009", "allowed_senders": ["+20 100 000 0002"]}))
    asyncio.run(channel._handle_inbound(_inbound("201000000009")))  # the old owner_number: no longer let in
    asyncio.run(channel._handle_inbound(_inbound("201000000002")))
    assert len(channel.emitted) == 1
    meta = channel.emitted[0].routing.metadata
    assert meta["sender_number"] == "201000000002"  # the core finds the person by it
    assert "route_to_default" not in meta


def test_a_group_message_is_ignored(channel) -> None:
    asyncio.run(channel.on_configure({"allowed_senders": ["201000000002"]}))
    asyncio.run(channel._handle_inbound(_inbound("201000000002", group=True)))
    assert channel.emitted == []


def test_with_no_list_nobody_passes(channel) -> None:
    asyncio.run(channel.on_configure({}))
    asyncio.run(channel._handle_inbound(_inbound("201000000002")))
    assert channel.emitted == []
