"""End to end: the core's ExtensionManager and the SDK's ExtensionClient.

Runs the real extension socket on a free local port with a temporary workspace,
and the real client against it: pairing with a code, both Phase 3 test calls,
a devices-only method refused, a wrong code, removal, and signing in again.
"""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hiro_channel_sdk.extension import (
    STATUS_CONNECTED,
    STATUS_NOT_PAIRED,
    ExtensionClient,
    ExtensionCredentials,
    ExtensionInfo,
    ExtensionRequestError,
)
from hirocli.domain.config import Config
from hirocli.domain.extensions import list_paired_extensions, remove_paired_extension, start_extension_pairing
from hirocli.runtime.extension_manager import ExtensionManager
from hirocli.runtime.request_handler import ALL_CALLERS, DEVICES_ONLY, RequestHandler
from hirocli.runtime.request_methods import handle_core_info


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _secret_history(params: dict[str, Any], ctx: Any) -> dict[str, Any]:
    return {"history": "only for the app"}


def _core(workspace: Path, port: int) -> tuple[ExtensionManager, SimpleNamespace]:
    ctx = SimpleNamespace(
        workspace_path=workspace,
        workspace_name="test",
        config=Config(extension_host="127.0.0.1", extension_port=port),
        stop_event=asyncio.Event(),
    )
    handler = RequestHandler(ctx)  # type: ignore[arg-type]
    handler.register("core.info", handle_core_info, callers=ALL_CALLERS)
    handler.register("messages.history", _secret_history, callers=DEVICES_ONLY)
    return ExtensionManager(ctx, handler), ctx  # type: ignore[arg-type]


async def _wait_for(predicate: Any, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.02)


def _client(port: int, folder: Path) -> ExtensionClient:
    return ExtensionClient(
        f"ws://127.0.0.1:{port}",
        ExtensionInfo(name="home", version="9.9.9"),
        ExtensionCredentials(folder),
    )


def test_pair_call_both_ways_remove_and_sign_in_again(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace = tmp_path / "ws"
        port = _free_port()
        manager, ctx = _core(workspace, port)
        server = asyncio.create_task(manager.run())
        await _wait_for(lambda: manager.listen_state()["listening"])

        client = _client(port, tmp_path / "home")
        runner = asyncio.create_task(client.run())
        await _wait_for(lambda: client.status == STATUS_NOT_PAIRED)

        # A wrong code is refused and the client waits for a new one.
        start_extension_pairing(workspace, code_length=6, ttl_seconds=60)
        client.pair("000000x")
        await _wait_for(lambda: client.status == STATUS_NOT_PAIRED and "error" in client.status_detail)

        session = start_extension_pairing(workspace, code_length=6, ttl_seconds=60)
        client.pair(session.code)
        await _wait_for(lambda: client.status == STATUS_CONNECTED)
        [paired] = list_paired_extensions(workspace)
        assert paired.name == "home"
        assert client.status_detail["core"]["name"] == "HiroLeague"

        # Test call 1: the extension asks the core.
        core = await client.request("core.info")
        assert core["name"] == "HiroLeague" and core["workspace"] == "test"
        # A devices-only method looks unknown to an extension.
        with pytest.raises(ExtensionRequestError) as err:
            await client.request("messages.history")
        assert err.value.code == "method_not_found"

        # Test call 2: the core asks the extension.
        info = await manager.request(paired.extension_id, "extension.info")
        # The whole self-description, uses included (Phase 7a's Uses page Refresh reads it).
        assert {k: info[k] for k in ("name", "version", "description", "uses")} == {
            "name": "home",
            "version": "9.9.9",
            "description": "",
            "uses": [],
        }

        # Restart of the extension: it signs in again with its key, no code.
        await client.stop()
        await runner
        client = _client(port, tmp_path / "home")
        runner = asyncio.create_task(client.run())
        await _wait_for(lambda: client.status == STATUS_CONNECTED)
        assert len(list_paired_extensions(workspace)) == 1

        # Removed in the admin: disconnected and refused; it waits for a new code.
        assert remove_paired_extension(workspace, paired.extension_id)
        await manager.disconnect(paired.extension_id)
        await _wait_for(lambda: client.status == STATUS_NOT_PAIRED)
        assert manager.snapshot() == {}

        await client.stop()
        await runner
        ctx.stop_event.set()
        await asyncio.wait_for(server, 5)

    asyncio.run(scenario())


def test_listen_failure_does_not_raise(tmp_path: Path) -> None:
    async def scenario() -> None:
        port = _free_port()
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", port))
            busy.listen()
            manager, _ = _core(tmp_path / "ws", port)
            await asyncio.wait_for(manager.run(), 5)  # returns instead of raising
            state = manager.listen_state()
            assert state["listening"] is False and state["error"]

    asyncio.run(scenario())
