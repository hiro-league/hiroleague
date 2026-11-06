"""channel.call: a named request the core waits on (Phase 4), answered by the plugin's on_call."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from hiro_channel_sdk import rpc
from hiro_channel_sdk.base import ChannelCallNotSupported, ChannelCallRefused, ChannelPlugin
from hiro_channel_sdk.constants import (
    JSONRPC_ERROR_CALL_REFUSED,
    JSONRPC_ERROR_METHOD_NOT_FOUND,
    METHOD_CALL,
)
from hiro_channel_sdk.models import ChannelInfo, RpcRequest, UnifiedMessage
from hiro_channel_sdk.transport import PluginTransport


class _Plugin(ChannelPlugin):
    @property
    def info(self) -> ChannelInfo:
        return ChannelInfo(name="test", version="0", description="")

    async def on_configure(self, config: dict[str, Any]) -> None: ...

    async def on_start(self) -> None: ...

    async def on_stop(self) -> None: ...

    async def send(self, message: UnifiedMessage) -> None: ...

    async def on_call(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        if name == "echo":
            return {"echo": params}
        if name == "refuse":
            raise ChannelCallRefused("not_connected", "Not connected")
        raise ChannelCallNotSupported(name)


class _Ws:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


def _answer(name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    transport = PluginTransport(_Plugin(), "ws://unused")
    ws = _Ws()
    transport._ws = ws
    req = RpcRequest.model_validate(
        json.loads(rpc.build_request(METHOD_CALL, {"name": name, "params": params or {}}, request_id="r1"))
    )
    asyncio.run(transport._dispatch(req))
    assert len(ws.sent) == 1
    return ws.sent[0]


def test_call_answers_with_the_result() -> None:
    assert _answer("echo", {"a": 1})["result"] == {"echo": {"a": 1}}


def test_refusal_carries_its_reason() -> None:
    error = _answer("refuse")["error"]
    assert error["code"] == JSONRPC_ERROR_CALL_REFUSED
    assert error["message"] == "Not connected"
    assert error["data"] == {"reason": "not_connected"}


def test_unknown_call_is_method_not_found() -> None:
    assert _answer("dance")["error"]["code"] == JSONRPC_ERROR_METHOD_NOT_FOUND


def test_plugins_without_on_call_say_not_supported() -> None:
    class Bare(_Plugin):
        on_call = ChannelPlugin.on_call  # type: ignore[assignment]

    transport = PluginTransport(Bare(), "ws://unused")
    ws = _Ws()
    transport._ws = ws
    req = RpcRequest(method=METHOD_CALL, params={"name": "x", "params": {}}, id="r2")
    asyncio.run(transport._dispatch(req))
    assert ws.sent[0]["error"]["code"] == JSONRPC_ERROR_METHOD_NOT_FOUND
