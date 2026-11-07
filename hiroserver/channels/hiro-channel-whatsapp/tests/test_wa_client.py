"""WhatsAppBridge on neonize 0.5.x: client lifecycle, LID senders, sends for an extension.

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
    "neonize.proto.waE2E",
    "neonize.proto.waE2E.WAWebProtobufsE2E_pb2",
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


# -- sends for an extension (Phase 4: HomeHiro's messages through the core) ------


class SendingClient(FakeClient):
    async def send_message(self, jid: Any, message: Any) -> None:
        self.calls.append(f"text:{jid.User}:{message}")

    async def send_image(self, jid: Any, image: bytes, caption: Any = None) -> None:
        self.calls.append(f"image:{jid.User}:{len(image)}:{caption}")

    async def is_on_whatsapp(self, *numbers: str) -> list[Any]:
        return [
            types.SimpleNamespace(Query=n, IsIn=n.endswith("9"), JID=types.SimpleNamespace(User=n, Server="s.whatsapp.net"))
            for n in numbers
        ]


@pytest.fixture
def plain_jids(wa_client, monkeypatch):
    monkeypatch.setattr(wa_client, "build_jid", lambda u, s: types.SimpleNamespace(User=u, Server=s))
    return wa_client


def test_extension_send_refused_while_not_connected(plain_jids, tmp_path):
    bridge = _bridge(plain_jids, tmp_path, SendingClient())  # never reported "connected"
    with pytest.raises(plain_jids.WhatsAppNotConnected):
        asyncio.run(bridge.send_for_extension("201001234569", text="hi"))


def test_extension_send_text_and_picture_once_connected(plain_jids, tmp_path):
    client = SendingClient()

    async def scenario() -> None:
        bridge = _bridge(plain_jids, tmp_path, client)
        await bridge._safe_status("connected", {})
        await bridge.send_for_extension("201001234569", text="Joe is home")
        await bridge.send_for_extension("201001234569@s.whatsapp.net", text="at the door", image=b"jpeg")
        await bridge._safe_status("disconnected", {})
        with pytest.raises(plain_jids.WhatsAppNotConnected):
            await bridge.send_for_extension("201001234569", text="again")

    asyncio.run(scenario())
    assert client.calls == ["text:201001234569:Joe is home", "image:201001234569:4:at the door"]


def test_number_check_answers_each_number(plain_jids, tmp_path):
    async def scenario() -> list[dict[str, Any]]:
        bridge = _bridge(plain_jids, tmp_path, SendingClient())
        await bridge._safe_status("connected", {})
        return await bridge.check_numbers(["201001234569", "201001234560"])

    answers = asyncio.run(scenario())
    assert answers == [
        {"query": "201001234569", "on_whatsapp": True, "jid": "201001234569@s.whatsapp.net"},
        {"query": "201001234560", "on_whatsapp": False, "jid": "201001234560@s.whatsapp.net"},
    ]


@pytest.fixture
def plugin_module(wa_client):
    sys.modules.pop("hiro_channel_whatsapp.plugin", None)
    module = importlib.import_module("hiro_channel_whatsapp.plugin")
    yield module
    sys.modules.pop("hiro_channel_whatsapp.plugin", None)


class FakeBridge:
    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self.error = error

    async def send_for_extension(self, to: str, **kwargs: Any) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append({"to": to, **kwargs})


def test_plugin_call_send_decodes_and_answers(plugin_module):
    plugin = plugin_module.WhatsAppChannel()
    bridge = FakeBridge()
    plugin._bridge = bridge
    result = asyncio.run(
        plugin.on_call("send", {"to": "201001234569", "voice_b64": "T2dnUw==", "voice_seconds": 2.4, "waveform_b64": "YWI="})
    )
    assert result == {"sent": True}
    assert bridge.sent == [
        {"to": "201001234569", "text": "", "image": None, "voice": b"OggS", "voice_seconds": 2.4, "waveform": b"ab"}
    ]


def test_plugin_call_send_says_why_not(plugin_module, wa_client):
    from hiro_channel_sdk.base import ChannelCallNotSupported, ChannelCallRefused

    plugin = plugin_module.WhatsAppChannel()
    with pytest.raises(ChannelCallRefused) as not_started:
        asyncio.run(plugin.on_call("send", {"to": "201001234569", "text": "hi"}))
    assert not_started.value.reason == "whatsapp_not_connected"

    plugin._bridge = FakeBridge(error=plugin_module.WhatsAppNotConnected("WhatsApp isn't connected"))
    with pytest.raises(ChannelCallRefused) as offline:
        asyncio.run(plugin.on_call("send", {"to": "201001234569", "text": "hi"}))
    assert offline.value.reason == "whatsapp_not_connected"

    plugin._bridge = FakeBridge(error=RuntimeError("usync timeout"))
    with pytest.raises(ChannelCallRefused) as failed:
        asyncio.run(plugin.on_call("send", {"to": "201001234569", "text": "hi"}))
    assert failed.value.reason == "whatsapp_failed"

    with pytest.raises(ChannelCallRefused) as bad:
        asyncio.run(plugin.on_call("send", {"to": "201001234569", "image_b64": "not base64!"}))
    assert bad.value.reason == "invalid_params"

    with pytest.raises(ChannelCallNotSupported):
        asyncio.run(plugin.on_call("dance", {}))
