"""Tests for ToolRegistry async dispatch / runtime injection and MessageSendTool."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME
from hirocli.domain.data_store import ensure_data_db
from hirocli.domain.conversation_channel import (
    CHAT_CHANNEL_LOCAL_ID_PREFIX,
    create_channel,
)
from hirocli.tools.base import Tool, ToolParam
from hirocli.tools.conversation import (
    SYNTHETIC_ADMIN_ORIGIN,
    SYNTHETIC_ADMIN_SENDER_ID,
    MessageSendResult,
    MessageSendTool,
)
from hirocli.tools.registry import (
    RuntimeContext,
    ToolAsyncOnlyError,
    ToolExecutionError,
    ToolRegistry,
)


class FakeCommManager:
    """Minimal stand-in — ``MessageSendTool`` only needs ``ctx.workspace_path`` and ``receive()``."""

    def __init__(self, workspace_path: Path) -> None:
        self.ctx = SimpleNamespace(workspace_path=workspace_path)
        self.calls: list[dict[str, Any]] = []

    async def receive(
        self,
        data: dict[str, Any],
        *,
        await_message_flow: bool = False,
    ) -> None:
        self.calls.append({"data": data, "await_message_flow": await_message_flow})


class EchoTool(Tool):
    runtime = False
    name = "echo_registry_test"
    description = "Test sync tool"
    params = {"s": ToolParam(str, "string to echo")}

    def execute(self, s: str) -> dict[str, str]:
        return {"echo": s}


class TracksRuntimeTool(Tool):
    runtime = True
    name = "tracks_runtime_registry_test"
    description = "Records attach_runtime ctx"
    params = {}

    def __init__(self) -> None:
        self.seen_runtime: RuntimeContext | None = None

    def attach_runtime(self, ctx: Any) -> None:
        self.seen_runtime = ctx

    def execute(self, **_: Any) -> str:
        return "unused"

    async def execute_async(self) -> dict[str, str]:
        rt = self.seen_runtime
        ok = rt is not None and rt.comm_manager is not None
        return {"attached": str(ok)}


@pytest.mark.asyncio
async def test_registry_invoke_async_uses_execute_async_when_present(tmp_path: Path) -> None:
    ensure_data_db(tmp_path)
    ch = create_channel(tmp_path, name="RegTestCh", character_id="c1")

    fake = FakeCommManager(tmp_path)
    loop = asyncio.get_running_loop()
    rctx = RuntimeContext(comm_manager=fake, loop=loop)

    reg = ToolRegistry(runtime=rctx)
    reg.register(MessageSendTool())

    out = await reg.invoke_async(
        "message_send",
        {"channel_id": ch.id, "text": " hello "},
    )
    assert isinstance(out.result, MessageSendResult)
    assert out.result.channel_id == ch.id

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["await_message_flow"] is True

    routing = call["data"]["routing"]
    assert routing["channel"] == MANDATORY_CHANNEL_NAME
    assert routing["sender_id"] == SYNTHETIC_ADMIN_SENDER_ID
    assert routing["metadata"]["origin"] == SYNTHETIC_ADMIN_ORIGIN
    # Wire ``chat_channel_id`` matches the form Flutter clients send
    # (``server-<id>``) so the live broadcast mirror is filed against the
    # device's local channel row, not against the raw int.
    assert (
        routing["metadata"]["chat_channel_id"]
        == f"{CHAT_CHANNEL_LOCAL_ID_PREFIX}{ch.id}"
    )
    assert call["data"]["content"][0]["content_type"] == "text"
    assert call["data"]["content"][0]["body"] == "hello"


@pytest.mark.asyncio
async def test_registry_invoke_async_to_thread_for_sync_tool() -> None:
    reg = ToolRegistry()
    reg.register(EchoTool())
    out = await reg.invoke_async("echo_registry_test", {"s": "ping"})
    assert out.result == {"echo": "ping"}


def test_registry_invoke_raises_tool_async_only_for_message_send() -> None:
    reg = ToolRegistry()
    reg.register(MessageSendTool())
    with pytest.raises(ToolAsyncOnlyError, match="invoke_async"):
        reg.invoke("message_send", {"channel_id": 1, "text": "x"})


@pytest.mark.asyncio
async def test_registry_invoke_async_wraps_missing_runtime_as_tool_execution_error(
    tmp_path: Path,
) -> None:
    ensure_data_db(tmp_path)
    ch = create_channel(tmp_path, name="NoRuntimeCh", character_id="c2")

    reg = ToolRegistry()
    reg.register(MessageSendTool())
    with pytest.raises(ToolExecutionError) as exc_info:
        await reg.invoke_async("message_send", {"channel_id": ch.id, "text": "x"})
    assert "runtime context" in str(exc_info.value.cause).lower()


@pytest.mark.asyncio
async def test_registry_register_attaches_runtime_for_runtime_tools(tmp_path: Path) -> None:
    fake = FakeCommManager(tmp_path)
    loop = asyncio.get_running_loop()
    rctx = RuntimeContext(comm_manager=fake, loop=loop)

    tool = TracksRuntimeTool()
    reg = ToolRegistry(runtime=rctx)
    reg.register(tool)

    assert tool.seen_runtime is rctx
    out = await reg.invoke_async("tracks_runtime_registry_test", {})
    assert out.result == {"attached": "True"}


@pytest.mark.asyncio
async def test_message_send_execute_async_audio_payload_metadata(tmp_path: Path) -> None:
    ensure_data_db(tmp_path)
    ch = create_channel(tmp_path, name="AudioCh", character_id="c3")

    fake = FakeCommManager(tmp_path)
    loop = asyncio.get_running_loop()
    tool = MessageSendTool()
    tool.attach_runtime(RuntimeContext(comm_manager=fake, loop=loop))

    raw = b"\x00\x01\x02"
    b64 = base64.b64encode(raw).decode("ascii")

    result = await tool.execute_async(
        ch.id,
        audio_base64=b64,
        audio_mime_type="audio/webm",
        audio_duration_ms=500,
    )

    assert result.message_id
    assert result.channel_id == ch.id

    assert len(fake.calls) == 1
    item = fake.calls[0]["data"]["content"][0]
    assert item["content_type"] == "audio"
    assert "blob_id" in item["metadata"]
    assert item["metadata"]["mime_type"] == "audio/webm"
    assert item["metadata"]["duration_ms"] == 500
    assert item["metadata"]["size"] == len(raw)
    assert item["metadata"]["chunk_count"] >= 1


@pytest.mark.asyncio
async def test_message_send_execute_async_rejects_workspace_mismatch(tmp_path: Path) -> None:
    ensure_data_db(tmp_path)
    ch = create_channel(tmp_path, name="WsCh", character_id="c4")

    other = tmp_path / "other_ws"
    other.mkdir()
    ensure_data_db(other)
    create_channel(other, name="Other", character_id="o1")

    fake = FakeCommManager(tmp_path)
    loop = asyncio.get_running_loop()
    tool = MessageSendTool()
    tool.attach_runtime(RuntimeContext(comm_manager=fake, loop=loop))

    with pytest.raises(ValueError, match="workspace"):
        await tool.execute_async(ch.id, workspace_path=other)


@pytest.mark.asyncio
async def test_message_send_execute_async_requires_exactly_one_body_source(tmp_path: Path) -> None:
    ensure_data_db(tmp_path)
    ch = create_channel(tmp_path, name="DupCh", character_id="c5")

    fake = FakeCommManager(tmp_path)
    loop = asyncio.get_running_loop()
    tool = MessageSendTool()
    tool.attach_runtime(RuntimeContext(comm_manager=fake, loop=loop))

    with pytest.raises(ValueError, match="exactly one"):
        await tool.execute_async(ch.id, text="a", audio_base64="eA==")
