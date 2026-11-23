"""Generic channel.status / channel.pairing infra handlers (design §5.4).

The handlers key the ctx status cache off the name of the channel plugin that sent the event (the extension manager
knows who signed in), so one handler pair serves every channel.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hirocli.runtime.infra_event_handlers import InfraEventHandlers

_NAMES = {"e-wa": "whatsapp", "e-tg": "telegram"}


def _handlers() -> InfraEventHandlers:
    # The pairing/status handlers only read/write ctx.channel_status.
    ctx = SimpleNamespace(channel_status={})
    handlers = InfraEventHandlers(ctx)  # type: ignore[arg-type]
    handlers._extensions = SimpleNamespace(name_of=lambda extension_id: _NAMES.get(extension_id, ""))  # type: ignore[assignment]
    return handlers


@pytest.mark.asyncio
async def test_pairing_cached_under_emitting_channel() -> None:
    h = _handlers()
    await h.handle_channel_pairing("e-wa", "channel.pairing", {"kind": "qr", "qr": "CODE123"})
    st = h._ctx.channel_status["whatsapp"]
    assert st["qr"] == "CODE123"
    assert st["pairing_kind"] == "qr"
    assert st["qr_at"]


@pytest.mark.asyncio
async def test_status_keyed_by_channel_and_drops_qr_on_connect() -> None:
    h = _handlers()
    # A second channel's status must not clobber the first.
    await h.handle_channel_pairing("e-wa", "channel.pairing", {"kind": "qr", "qr": "CODE"})
    await h.handle_channel_status("e-tg", "channel.status", {"state": "connected", "account": "bot42"})
    await h.handle_channel_status("e-wa", "channel.status", {"state": "connected", "reason": "linked"})
    wa = h._ctx.channel_status["whatsapp"]
    tg = h._ctx.channel_status["telegram"]
    assert wa["state"] == "connected"
    assert "qr" not in wa  # dropped once linked
    assert wa["detail"] == {"reason": "linked"}
    assert tg["state"] == "connected" and tg["account"] == "bot42"


@pytest.mark.asyncio
async def test_events_from_an_unknown_sender_are_ignored() -> None:
    h = _handlers()
    await h.handle_channel_status("e-gone", "channel.status", {"state": "connected"})  # no longer connected
    await h.handle_channel_pairing("e-gone", "channel.pairing", {"kind": "qr", "qr": "X"})
    assert h._ctx.channel_status == {}
