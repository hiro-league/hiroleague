"""End to end: a channel plugin on the one extension socket.

The real ExtensionManager on a free local port with a temporary workspace, and a plugin run by the SDK's PluginRunner
in this process: it pairs with the code the manager made for it, is given its settings and starts, relays a phone's
message in and a reply out, answers its own methods (a refusal keeps its code), and sends its events as itself. A lost
key pairs again and keeps the id; a used code is refused. An app may not relay: its frame for someone else is kept as
its own and never reaches chat.
"""

from __future__ import annotations

import asyncio
import shutil
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hiro_channel_sdk.base import ChannelCallNotSupported, ChannelCallRefused, ChannelPlugin
from hiro_channel_sdk.extension import (
    STATUS_CONNECTED,
    ExtensionClient,
    ExtensionCredentials,
    ExtensionInfo,
)
from hiro_channel_sdk.models import ChannelInfo, ContentItem, MessageRouting, UnifiedMessage
from hiro_channel_sdk.runner import PluginRunner
from hirocli.domain.channel_config import ChannelConfig, save_channel_config
from hirocli.domain.config import Config
from hirocli.domain.extensions import KIND_APP, KIND_CHANNEL, list_paired_extensions, start_extension_pairing
from hirocli.runtime.extension_manager import ChannelCallError, ExtensionManager
from hirocli.runtime.request_handler import RequestHandler

CHANNELS_ONLY = frozenset({KIND_CHANNEL})
APPS_ONLY = frozenset({KIND_APP})


class _Plugin(ChannelPlugin):
    def __init__(self) -> None:
        self.config: dict[str, Any] | None = None
        self.starts = 0
        self.sent: list[UnifiedMessage] = []
        self.events: list[tuple[str, dict[str, Any]]] = []

    @property
    def info(self) -> ChannelInfo:
        return ChannelInfo(name="echo", version="1.0", description="test", config_schema={"type": "object"})

    async def on_configure(self, config: dict[str, Any]) -> None:
        self.config = config

    async def on_start(self) -> None:
        self.starts += 1

    async def on_stop(self) -> None: ...

    async def send(self, message: UnifiedMessage) -> None:
        self.sent.append(message)

    async def on_event(self, event: str, data: dict[str, Any]) -> None:
        self.events.append((event, data))

    async def on_call(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        if name == "echo":
            return {"echo": params}
        if name == "refuse":
            raise ChannelCallRefused("not_linked", "Not linked yet")
        raise ChannelCallNotSupported(name)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _wait_for(predicate: Any, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.02)


def _core(workspace: Path, port: int) -> tuple[ExtensionManager, list[dict[str, Any]]]:
    ctx = SimpleNamespace(
        workspace_path=workspace,
        workspace_name="test",
        config=Config(extension_host="127.0.0.1", extension_port=port),
        stop_event=asyncio.Event(),
        device_names=SimpleNamespace(resolve=lambda device_id: device_id),
        log_dir=workspace / "logs",
    )
    manager = ExtensionManager(ctx, RequestHandler(ctx))  # type: ignore[arg-type]
    chat: list[dict[str, Any]] = []

    async def to_chat(data: dict[str, Any]) -> None:
        chat.append(data)

    manager.set_chat_handler(to_chat)
    return manager, chat


def _message(sender: str, channel: str, text: str, *, recipient: str | None = None) -> UnifiedMessage:
    return UnifiedMessage(
        routing=MessageRouting(channel=channel, direction="inbound" if recipient is None else "outbound",
                               sender_id=sender, recipient_id=recipient),
        content=[ContentItem(content_type="text", body=text)],
    )


def test_a_channel_plugin_pairs_starts_relays_and_answers(tmp_path: Path, caplog) -> None:
    caplog.set_level("INFO", logger="EXTENSIONS")

    async def scenario() -> None:
        workspace = tmp_path / "ws"
        # Off: the test runs the plugin itself, the manager doesn't start a process
        save_channel_config(workspace, ChannelConfig(name="echo", enabled=False, config={"greeting": "hi"}))
        port = _free_port()
        manager, chat = _core(workspace, port)
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def on_status(extension_id: str, event: str, data: dict[str, Any]) -> None:
            events.append((extension_id, event, data))

        manager.register_event_handler("channel.status", on_status, CHANNELS_ONLY)
        manager.register_event_handler("home.changed", on_status, APPS_ONLY)
        server = asyncio.create_task(manager.run())
        await _wait_for(lambda: manager.listen_state()["listening"])

        plugin = _Plugin()
        keys = tmp_path / "keys"
        runner = PluginRunner(plugin, f"ws://127.0.0.1:{port}", keys, pairing_code=manager._new_start_code("echo"))
        running = asyncio.create_task(runner.run())

        # Paired with the manager's code, given its settings, started once
        await _wait_for(lambda: plugin.starts == 1)
        assert plugin.config == {"greeting": "hi"}
        [row] = list_paired_extensions(workspace, kind=None)
        assert (row.name, row.kind, row.relays_chat, row.started_by_core) == ("echo", KIND_CHANNEL, True, True)
        assert row.public_key and ExtensionCredentials(keys).extension_id() == row.extension_id
        assert manager.snapshot() == {}  # apps only
        assert manager.get_connected_channels() == ["echo"]

        # A phone's message in, to chat; the reply out, to the plugin's send
        await plugin.emit(_message("phone-1", "echo", "hello"))
        await _wait_for(lambda: len(chat) == 1)
        assert chat[0]["routing"]["sender_id"] == "phone-1"
        reply = _message("server", "echo", "hello back", recipient="phone-1")
        await manager.send_to_channel("echo", reply.model_dump(mode="json"))
        await _wait_for(lambda: len(plugin.sent) == 1)
        assert plugin.sent[0].content[0].body == "hello back"

        # Its own methods: an answer, a refusal with its code, one it doesn't have
        assert await manager.call_channel("echo", "echo", {"a": 1}) == {"echo": {"a": 1}}
        with pytest.raises(ChannelCallError) as refused:
            await manager.call_channel("echo", "refuse")
        assert (refused.value.reason, str(refused.value)) == ("not_linked", "Not linked yet")
        with pytest.raises(ChannelCallError) as unknown:
            await manager.call_channel("echo", "dance")
        assert unknown.value.reason == "method_not_found"
        with pytest.raises(ChannelCallError) as absent:
            await manager.call_channel("whatsapp", "send")
        assert absent.value.reason == "not_running"

        # Its events, as itself: one open to channels reaches its handler; one open to apps only doesn't
        await plugin.emit_event("channel.status", {"state": "connected"})
        await plugin.emit_event("home.changed", {})
        await _wait_for(lambda: len(events) == 1)
        await asyncio.sleep(0.1)
        assert events == [(row.extension_id, "channel.status", {"state": "connected"})]
        # An admin action reaches its on_event
        await manager.send_event_to_channel("echo", "channel.logout", {})
        await _wait_for(lambda: plugin.events == [("channel.logout", {})])

        # A lost key: pairs again with a new code, keeps its id
        runner.stop()
        await asyncio.wait_for(running, 5)
        shutil.rmtree(keys)
        second_code = manager._new_start_code("echo")
        again = PluginRunner(_Plugin(), f"ws://127.0.0.1:{port}", keys, pairing_code=second_code)
        running = asyncio.create_task(again.run())
        await _wait_for(lambda: manager.get_connected_channels() == ["echo"])
        [row_again] = list_paired_extensions(workspace, kind=None)
        assert row_again.extension_id == row.extension_id and row_again.public_key != row.public_key
        again.stop()
        await asyncio.wait_for(running, 5)

        # The code it just paired with, again, with no key: a code works once, so it is refused and the runner ends
        shutil.rmtree(keys)
        used = PluginRunner(_Plugin(), f"ws://127.0.0.1:{port}", keys, pairing_code=second_code)
        await asyncio.wait_for(used.run(), 10)
        assert manager.get_connected_channels() == []
        assert any(r.levelname == "WARNING" and "Extension refused" in r.getMessage() and "bad_code" in r.getMessage()
                   for r in caplog.records)

        manager._ctx.stop_event.set()
        await asyncio.wait_for(server, 5)

    asyncio.run(scenario())


def test_an_app_may_not_relay_chat(tmp_path: Path, caplog) -> None:
    caplog.set_level("INFO", logger="EXTENSIONS")

    async def scenario() -> None:
        workspace = tmp_path / "ws"
        port = _free_port()
        manager, chat = _core(workspace, port)
        server = asyncio.create_task(manager.run())
        await _wait_for(lambda: manager.listen_state()["listening"])

        code = start_extension_pairing(workspace, code_length=6, ttl_seconds=60).code
        client = ExtensionClient(f"ws://127.0.0.1:{port}", ExtensionInfo(name="home"), ExtensionCredentials(tmp_path / "home"))
        client.pair(code)
        running = asyncio.create_task(client.run())
        await _wait_for(lambda: client.status == STATUS_CONNECTED)
        [app] = list_paired_extensions(workspace)
        assert (app.kind, app.relays_chat, app.started_by_core) == (KIND_APP, False, False)

        # A frame claiming to be a WhatsApp contact's: kept as the app's own, never chat
        assert await client.send_frame(_message("201000000000", "whatsapp", "let me in"))
        await asyncio.sleep(0.3)
        assert chat == []
        [kept] = [r for r in caplog.records if "kept as its own" in r.getMessage()]
        assert kept.levelname == "WARNING" and "home" in kept.getMessage()

        await client.stop()
        await asyncio.wait_for(running, 5)
        manager._ctx.stop_event.set()
        await asyncio.wait_for(server, 5)

    asyncio.run(scenario())
