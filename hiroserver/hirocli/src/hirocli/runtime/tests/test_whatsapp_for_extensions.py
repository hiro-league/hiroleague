"""Phase 4: an extension's WhatsApp messages go out through the core.

The three extension-only requests (whatsapp.send / check / status) against a fake
ChannelManager, a message to the owner landing in the owner's conversation and in
Hiro's thread, and ChannelManager.call_channel keeping the plugin's refusal reason.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hiro_channel_sdk.constants import (
    WHATSAPP_ERROR_NOT_CONNECTED,
    WHATSAPP_ERROR_NOT_RUNNING,
)
from hirocli.domain.channel_config import ChannelConfig, save_channel_config
from hirocli.domain.conversation_channel import resolve_default_channel
from hirocli.domain.message_store import list_messages
from hirocli.runtime.channel_manager import ChannelCallError, ChannelManager, _ConnectedChannel
from hirocli.runtime.request_handler import RequestRefused
from hirocli.runtime.whatsapp_for_extensions import (
    handle_whatsapp_check,
    handle_whatsapp_send,
    handle_whatsapp_status,
)

OWNER = "201001234569"


class FakeChannels:
    def __init__(self, error: ChannelCallError | None = None, connected: bool = True) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.error = error
        self.connected = connected

    async def call_channel(self, channel: str, name: str, params: dict[str, Any], *, timeout: float) -> Any:
        self.calls.append((channel, name, params))
        if self.error is not None:
            raise self.error
        if name == "check":
            return {"answers": [{"query": n, "on_whatsapp": True, "jid": f"{n}@s.whatsapp.net"} for n in params["numbers"]]}
        return {"sent": True}

    def get_connected_channels(self) -> list[str]:
        return ["devices", "whatsapp"] if self.connected else ["devices"]


class FakeAgent:
    def __init__(self) -> None:
        self.added: list[tuple[int, str]] = []

    async def add_sent_message(self, chat_channel_id: int, text: str) -> bool:
        self.added.append((chat_channel_id, text))
        return True


def _ctx(workspace: Path, channels: FakeChannels | None, agent: FakeAgent | None = None) -> SimpleNamespace:
    server_ctx = SimpleNamespace(
        workspace_path=workspace,
        channel_manager=channels,
        agent_manager=agent,
        extension_manager=None,
        channel_status={},
    )
    msg = SimpleNamespace(routing=SimpleNamespace(sender_id="ext-home"))
    return SimpleNamespace(server_ctx=server_ctx, msg=msg, workspace_path=workspace)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    save_channel_config(tmp_path, ChannelConfig(name="whatsapp", config={"owner_number": f"+{OWNER}"}))
    return tmp_path


def _bodies(workspace: Path) -> list[str]:
    conv = resolve_default_channel(workspace)
    rows = asyncio.run(list_messages(workspace, int(conv.id)))
    return [row["body"] for row in rows]


def test_send_to_someone_else_is_only_sent(workspace: Path) -> None:
    channels, agent = FakeChannels(), FakeAgent()
    result = asyncio.run(handle_whatsapp_send({"to": "201112223334", "text": "Dinner's ready"}, _ctx(workspace, channels, agent)))
    assert result == {"sent": True}
    assert channels.calls == [("whatsapp", "send", {"to": "201112223334", "text": "Dinner's ready"})]
    assert agent.added == []
    assert _bodies(workspace) == []


def test_send_to_the_owner_lands_in_the_conversation_and_hiros_thread(workspace: Path) -> None:
    channels, agent = FakeChannels(), FakeAgent()
    params = {"to": f"{OWNER}@s.whatsapp.net", "text": "Joe is home", "image_b64": "anBlZw=="}
    asyncio.run(handle_whatsapp_send(params, _ctx(workspace, channels, agent)))
    assert _bodies(workspace) == ["Joe is home (with a picture)"]
    assert [text for _, text in agent.added] == ["Joe is home (with a picture)"]


def test_voice_note_to_the_owner_records_its_transcript_but_never_sends_it(workspace: Path) -> None:
    channels, agent = FakeChannels(), FakeAgent()
    params = {"to": OWNER, "voice_b64": "T2dnUw==", "voice_seconds": 3, "transcript": "Dinner in ten"}
    asyncio.run(handle_whatsapp_send(params, _ctx(workspace, channels, agent)))
    assert "transcript" not in channels.calls[0][2]
    assert _bodies(workspace) == ["(voice note) Dinner in ten"]


def test_send_says_why_not(workspace: Path) -> None:
    with pytest.raises(RequestRefused) as missing:
        asyncio.run(handle_whatsapp_send({"text": "hi"}, _ctx(workspace, FakeChannels())))
    assert missing.value.code == "invalid_params"

    with pytest.raises(RequestRefused) as both:
        asyncio.run(handle_whatsapp_send({"to": OWNER, "image_b64": "eA==", "voice_b64": "eA=="}, _ctx(workspace, FakeChannels())))
    assert both.value.code == "invalid_params"

    not_running = FakeChannels(error=ChannelCallError("The whatsapp channel isn't running", "not_running"))
    with pytest.raises(RequestRefused) as off:
        asyncio.run(handle_whatsapp_send({"to": OWNER, "text": "hi"}, _ctx(workspace, not_running)))
    assert off.value.code == WHATSAPP_ERROR_NOT_RUNNING

    offline = FakeChannels(error=ChannelCallError("WhatsApp isn't connected", WHATSAPP_ERROR_NOT_CONNECTED))
    with pytest.raises(RequestRefused) as down:
        asyncio.run(handle_whatsapp_send({"to": OWNER, "text": "hi"}, _ctx(workspace, offline, FakeAgent())))
    assert down.value.code == WHATSAPP_ERROR_NOT_CONNECTED
    assert _bodies(workspace) == []  # not sent → not recorded


def test_check_passes_numbers_and_limits_them(workspace: Path) -> None:
    channels = FakeChannels()
    result = asyncio.run(handle_whatsapp_check({"numbers": [OWNER]}, _ctx(workspace, channels)))
    assert result["answers"][0]["on_whatsapp"] is True
    with pytest.raises(RequestRefused):
        asyncio.run(handle_whatsapp_check({"numbers": [str(n) for n in range(21)]}, _ctx(workspace, channels)))


def test_status_reports_the_plugins_last_state(workspace: Path) -> None:
    ctx = _ctx(workspace, FakeChannels())
    ctx.server_ctx.channel_status["whatsapp"] = {"state": "connected", "detail": {}, "account": OWNER}
    assert asyncio.run(handle_whatsapp_status({}, ctx)) == {
        "running": True, "state": "connected", "detail": {}, "waiting_for_link": False, "account": OWNER,
    }
    stopped = _ctx(workspace, FakeChannels(connected=False))
    assert asyncio.run(handle_whatsapp_status({}, stopped))["running"] is False


class _AnsweringWs:
    """A plugin socket that answers every channel.call with a refusal."""

    def __init__(self, manager: ChannelManager) -> None:
        self.manager = manager

    async def send(self, raw: str) -> None:
        req = json.loads(raw)
        reply = {"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32000, "message": "WhatsApp isn't connected", "data": {"reason": WHATSAPP_ERROR_NOT_CONNECTED}}}
        asyncio.get_running_loop().call_soon(
            lambda: asyncio.ensure_future(self.manager._handle_response("whatsapp", reply))
        )


def test_call_channel_keeps_the_plugins_reason() -> None:
    manager = ChannelManager(SimpleNamespace(config=SimpleNamespace(plugin_port=0)))  # type: ignore[arg-type]

    async def scenario() -> ChannelCallError:
        manager._channels["whatsapp"] = _ConnectedChannel(
            name="whatsapp", version="0", description="", ws=_AnsweringWs(manager)  # type: ignore[arg-type]
        )
        with pytest.raises(ChannelCallError) as refused:
            await manager.call_channel("whatsapp", "send", {"to": OWNER})
        with pytest.raises(ChannelCallError) as absent:
            await manager.call_channel("telegram", "send", {})
        assert absent.value.reason == "not_running"
        return refused.value

    refused = asyncio.run(scenario())
    assert refused.reason == WHATSAPP_ERROR_NOT_CONNECTED
    assert str(refused) == "WhatsApp isn't connected"
