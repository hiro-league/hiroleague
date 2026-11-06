"""WhatsAppBridge on neonize 0.5.x: client lifecycle and LID senders.

neonize 0.5.x's idle() only returns after Stop() (not Disconnect()), WhatsApp's QR
window expires silently, and a Disconnect() after Stop() panics in Go. These tests
drive the bridge with a fake client so they need neither neonize nor WhatsApp: the
shared dev venv can't import neonize 0.5.x anyway (it needs protobuf 7).
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from typing import Any

import pytest

_NEONIZE_MODULES = (
    "neonize",
    "neonize.aioze",
    "neonize.aioze.client",
    "neonize.aioze.events",
    "neonize.exc",
    "neonize.proto",
    "neonize.proto.waCompanionReg",
    "neonize.proto.waCompanionReg.WAWebProtobufsCompanionReg_pb2",
    "neonize.utils",
    "neonize.utils.enum",
)


class _Anything:
    """Stands in for any neonize class/enum/function the module imports."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        return _Anything()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return _Anything()


def _stub_module(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__getattr__ = lambda attr: _Anything()  # type: ignore[attr-defined]
    module.__path__ = []  # type: ignore[attr-defined]  # importable as a package
    return module


class FakeClient:
    """Records the calls the bridge makes, like neonize's NewAClient would see them."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def disconnect(self) -> None:
        if "stop" in self.calls:
            raise AssertionError("Disconnect after Stop panics in neonize's Go code")
        self.calls.append("disconnect")

    async def stop(self) -> None:
        self.calls.append("stop")

    async def logout(self) -> None:
        self.calls.append("logout")


@pytest.fixture
def wa_client(monkeypatch: pytest.MonkeyPatch):
    for name in _NEONIZE_MODULES:
        monkeypatch.setitem(sys.modules, name, _stub_module(name))
    monkeypatch.delitem(sys.modules, "hiro_channel_whatsapp.wa_client", raising=False)
    module = importlib.import_module("hiro_channel_whatsapp.wa_client")
    yield module
    sys.modules.pop("hiro_channel_whatsapp.wa_client", None)


async def _noop(*_args: Any) -> None:
    return None


def _bridge(wa_client, tmp_path, client: FakeClient):
    bridge = wa_client.WhatsAppBridge(
        str(tmp_path / "session.db"), on_qr=_noop, on_status=_noop, on_message=_noop
    )
    bridge._client = client
    return bridge


def test_unscanned_qr_window_stops_the_client(wa_client, tmp_path, monkeypatch):
    # Shrink the window so the watchdog fires within the test.
    monkeypatch.setattr(wa_client, "_QR_FIRST_CODE_S", 0.01)
    monkeypatch.setattr(wa_client, "_QR_NEXT_CODE_S", 0.01)
    monkeypatch.setattr(wa_client, "_QR_GRACE_S", 0.01)
    client = FakeClient()

    async def scenario() -> None:
        bridge = _bridge(wa_client, tmp_path, client)
        await bridge._on_qr_event(client, b"2@code")
        await asyncio.sleep(0.1)

    asyncio.run(scenario())
    assert client.calls == ["disconnect", "stop"]


def test_pairing_cancels_the_qr_watchdog(wa_client, tmp_path, monkeypatch):
    monkeypatch.setattr(wa_client, "_QR_FIRST_CODE_S", 0.05)
    monkeypatch.setattr(wa_client, "_QR_GRACE_S", 0.0)
    client = FakeClient()

    async def scenario() -> None:
        bridge = _bridge(wa_client, tmp_path, client)
        await bridge._on_qr_event(client, b"2@code")
        await bridge._on_connected(client, None)
        await asyncio.sleep(0.15)

    asyncio.run(scenario())
    assert client.calls == []


def test_client_is_stopped_only_once(wa_client, tmp_path):
    # Reconnect, then the plugin shutting down: the second must not Disconnect a
    # client neonize already deleted (that panics in Go).
    client = FakeClient()

    async def scenario() -> None:
        bridge = _bridge(wa_client, tmp_path, client)
        await bridge.reconnect()
        await bridge.stop()
        await bridge.logout()

    asyncio.run(scenario())
    assert client.calls == ["disconnect", "stop"]


class HangingClient(FakeClient):
    """idle() never returns, like neonize 0.5.x stopped mid-QR-window."""

    async def connect(self) -> None:
        self.calls.append("connect")

    async def idle(self) -> None:
        await asyncio.Event().wait()


def test_run_moves_on_when_a_stopped_client_hangs(wa_client, tmp_path, monkeypatch):
    monkeypatch.setattr(wa_client, "_STOPPED_IDLE_GRACE_S", 0.01)
    clients: list[HangingClient] = []

    async def scenario() -> None:
        bridge = wa_client.WhatsAppBridge(
            str(tmp_path / "session.db"), on_qr=_noop, on_status=_noop, on_message=_noop
        )

        def build() -> HangingClient:
            client = HangingClient()
            clients.append(client)
            bridge._client = client
            bridge._client_ended = False
            bridge._client_ended_event = asyncio.Event()
            return client

        monkeypatch.setattr(bridge, "_build_client", build)
        monkeypatch.setattr(bridge, "_enable_receipts", _noop)
        runner = asyncio.ensure_future(bridge.run())
        await asyncio.sleep(0.05)
        await bridge._end_client(clients[0])  # e.g. the QR watchdog fired
        await asyncio.sleep(1.5)  # grace + run()'s 1 s reconnect backoff
        await bridge.stop()
        await asyncio.wait_for(runner, 1)  # stop() ends run() even with a hung client

    asyncio.run(scenario())
    assert len(clients) >= 2, "run() stayed on the hung client"
    assert clients[0].calls == ["connect", "disconnect", "stop"]


class LidClient(FakeClient):
    async def get_pn_from_lid(self, jid: Any) -> Any:
        return types.SimpleNamespace(User="201223504849", Server="s.whatsapp.net")


def _lid_event() -> Any:
    lid = types.SimpleNamespace(User="59515412152504", Server="lid")
    source = types.SimpleNamespace(Sender=lid, Chat=lid)
    return types.SimpleNamespace(Info=types.SimpleNamespace(MessageSource=source))


def test_lid_sender_gets_its_phone_number_for_the_allow_list(wa_client, tmp_path, monkeypatch):
    # neonize 0.5.x: a direct message from a LID contact carries no SenderAlt, so
    # _extract_inbound leaves sender_pn empty and the reply target is the @lid.
    monkeypatch.setattr(wa_client, "Jid2String", lambda j: f"{j.User}@{j.Server}")
    monkeypatch.setattr(wa_client, "build_jid", lambda u, s: types.SimpleNamespace(User=u, Server=s))
    monkeypatch.setattr(wa_client, "JIDToNonAD", lambda j: j)
    inbound = {"reply_jid": "59515412152504@lid", "sender_pn": ""}

    async def scenario() -> None:
        bridge = _bridge(wa_client, tmp_path, LidClient())
        await bridge._resolve_lid_sender(inbound, _lid_event())

    asyncio.run(scenario())
    assert inbound["sender_pn"] == "201223504849"
    assert inbound["reply_jid"] == "201223504849@s.whatsapp.net"


def test_logout_unlinks_then_stops(wa_client, tmp_path):
    client = FakeClient()

    async def scenario() -> None:
        bridge = _bridge(wa_client, tmp_path, client)
        await bridge.logout()

    asyncio.run(scenario())
    assert client.calls == ["logout", "disconnect", "stop"]
