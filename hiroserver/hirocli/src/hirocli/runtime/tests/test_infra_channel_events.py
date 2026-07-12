"""Generic channel.status / channel.pairing infra handlers (design §5.4).

The handlers key the ctx status cache off the channel name that ChannelManager
injects into the event data, so one handler pair serves every channel.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hirocli.runtime.infra_event_handlers import InfraEventHandlers


def _handlers() -> InfraEventHandlers:
    # The pairing/status handlers only read/write ctx.channel_status.
    ctx = SimpleNamespace(channel_status={})
    return InfraEventHandlers(ctx)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_pairing_cached_under_emitting_channel() -> None:
    h = _handlers()
    await h.handle_channel_pairing({"channel": "whatsapp", "kind": "qr", "qr": "CODE123"})
    st = h._ctx.channel_status["whatsapp"]
    assert st["qr"] == "CODE123"
    assert st["pairing_kind"] == "qr"
    assert st["qr_at"]


@pytest.mark.asyncio
async def test_status_keyed_by_channel_and_drops_qr_on_connect() -> None:
    h = _handlers()
    # A second channel's status must not clobber the first.
    await h.handle_channel_pairing({"channel": "whatsapp", "kind": "qr", "qr": "CODE"})
    await h.handle_channel_status(
        {"channel": "telegram", "state": "connected", "account": "bot42"}
    )
    await h.handle_channel_status(
        {"channel": "whatsapp", "state": "connected", "reason": "linked"}
    )
    wa = h._ctx.channel_status["whatsapp"]
    tg = h._ctx.channel_status["telegram"]
    assert wa["state"] == "connected"
    assert "qr" not in wa  # dropped once linked
    assert wa["detail"] == {"reason": "linked"}  # 'channel' excluded from detail
    assert tg["state"] == "connected" and tg["account"] == "bot42"


@pytest.mark.asyncio
async def test_events_without_channel_are_ignored() -> None:
    h = _handlers()
    await h.handle_channel_status({"state": "connected"})  # no channel
    await h.handle_channel_pairing({"kind": "qr", "qr": "X"})  # no channel
    assert h._ctx.channel_status == {}
