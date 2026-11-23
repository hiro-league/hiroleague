"""PluginRunner: a channel plugin's API on the extension client.

The plugin's own methods answer requests (a refusal carries its code), its settings start it once, a frame for
someone else goes to its send, and the pairing code comes from its environment. (Signing in against the real manager:
hirocli runtime/tests/test_extension_manager_channels.py.)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from hiro_channel_sdk.base import ChannelCallNotSupported, ChannelCallRefused, ChannelPlugin
from hiro_channel_sdk.constants import ENV_PAIRING_CODE
from hiro_channel_sdk.extension import ExtensionRequestError
from hiro_channel_sdk.models import ChannelInfo, ContentItem, MessageRouting, UnifiedMessage
from hiro_channel_sdk.runner import PluginRunner


class _Plugin(ChannelPlugin):
    def __init__(self) -> None:
        self.configs: list[dict[str, Any]] = []
        self.starts = 0
        self.sent: list[UnifiedMessage] = []

    @property
    def info(self) -> ChannelInfo:
        return ChannelInfo(name="test", version="0", description="", capabilities={"pairing": "qr"})

    async def on_configure(self, config: dict[str, Any]) -> None:
        self.configs.append(config)

    async def on_start(self) -> None:
        self.starts += 1

    async def on_stop(self) -> None: ...

    async def send(self, message: UnifiedMessage) -> None:
        self.sent.append(message)

    async def on_call(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        if name == "echo":
            return {"echo": params}
        if name == "refuse":
            raise ChannelCallRefused("not_connected", "Not connected")
        raise ChannelCallNotSupported(name)


def _runner(tmp_path: Path, plugin: ChannelPlugin | None = None, code: str | None = None) -> PluginRunner:
    return PluginRunner(plugin or _Plugin(), "ws://unused", tmp_path / "keys", pairing_code=code)


def test_a_call_answers_with_the_result(tmp_path: Path) -> None:
    assert asyncio.run(_runner(tmp_path)._call("echo", {"a": 1})) == {"echo": {"a": 1}}


def test_a_refusal_carries_its_code(tmp_path: Path) -> None:
    with pytest.raises(ExtensionRequestError) as refused:
        asyncio.run(_runner(tmp_path)._call("refuse", {}))
    assert (refused.value.code, refused.value.message) == ("not_connected", "Not connected")


def test_an_unknown_call_is_method_not_found(tmp_path: Path) -> None:
    with pytest.raises(ExtensionRequestError) as unknown:
        asyncio.run(_runner(tmp_path)._call("dance", {}))
    assert unknown.value.code == "method_not_found"


def test_settings_start_the_plugin_once(tmp_path: Path) -> None:
    plugin = _Plugin()
    runner = _runner(tmp_path, plugin)

    async def scenario() -> None:
        await runner._configure({"config": {"a": 1}})
        await runner._configure({"config": {"a": 2}})  # saved again while it runs

    asyncio.run(scenario())
    assert (plugin.configs, plugin.starts) == ([{"a": 1}, {"a": 2}], 1)


def test_a_frame_for_someone_else_goes_to_send(tmp_path: Path) -> None:
    plugin = _Plugin()
    msg = UnifiedMessage(routing=MessageRouting(channel="test", direction="outbound", sender_id="server",
                                                recipient_id="phone-1"),
                         content=[ContentItem(content_type="text", body="hi")])
    asyncio.run(_runner(tmp_path, plugin)._relay(msg))
    assert plugin.sent == [msg]


def test_the_description_carries_the_plugins_settings_form_and_link_steps(tmp_path: Path) -> None:
    info = _runner(tmp_path).client._info  # noqa: SLF001
    assert (info.name, info.capabilities, info.config_schema) == ("test", {"pairing": "qr"}, None)


def test_the_pairing_code_comes_from_the_environment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(ENV_PAIRING_CODE, " abc123 ")
    assert _runner(tmp_path)._code == "abc123"
    monkeypatch.delenv(ENV_PAIRING_CODE)
    assert _runner(tmp_path)._code is None
