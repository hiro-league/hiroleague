"""The logging plan's one id across the apps, end to end on the real extension socket: an app's request carries its
story into the core (the frame's traceparent), the core's handler runs in it, and an ask passed on to another app
(extensions.ask) arrives in the same story."""

from __future__ import annotations

from hirocli.runtime.tests.approved import approve_every_app

import asyncio
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hiro_channel_sdk.extension import (
    STATUS_CONNECTED,
    STATUS_NOT_PAIRED,
    ExtensionClient,
    ExtensionCredentials,
    ExtensionInfo,
    ExtensionOffers,
)
from hiro_commons.logging_foundation import story

from hirocli.domain.config import Config
from hirocli.domain.extensions import start_extension_pairing
from hirocli.runtime.asks_between_extensions import ASK_REQUEST_HANDLERS
from hirocli.runtime.extension_manager import ExtensionManager
from hirocli.runtime.request_handler import CALLER_EXTENSION, RequestHandler

STORY = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT = f"00-{STORY}-00f067aa0ba902b7-01"


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


async def _connect(workspace: Path, port: int, folder: Path, info: ExtensionInfo) -> tuple[ExtensionClient, asyncio.Task]:
    client = ExtensionClient(f"ws://127.0.0.1:{port}", info, ExtensionCredentials(folder))
    running = asyncio.create_task(client.run())
    await _wait_for(lambda: client.status == STATUS_NOT_PAIRED)
    client.pair(start_extension_pairing(workspace, code_length=6, ttl_seconds=60).code)
    await _wait_for(lambda: client.status == STATUS_CONNECTED)
    approve_every_app(workspace)  # Permissions phase 8: not what this test is about
    return client, running


def test_a_story_goes_from_an_app_through_the_core_to_another_app(tmp_path: Path) -> None:
    in_core: list[str | None] = []
    in_net: list[str | None] = []

    async def core_info(params: dict[str, Any], ctx: Any) -> dict[str, Any]:
        in_core.append(story.current_id())
        return {"name": "HiroLeague"}

    async def net_usage(params: dict[str, Any]) -> dict[str, Any]:
        in_net.append(story.current_id())
        return {"bytes": 42}

    async def scenario() -> None:
        workspace, port = tmp_path / "ws", _free_port()
        ctx = SimpleNamespace(workspace_path=workspace, workspace_name="test",
                              config=Config(extension_host="127.0.0.1", extension_port=port),
                              stop_event=asyncio.Event(), extension_manager=None)
        handler = RequestHandler(ctx)  # type: ignore[arg-type]
        handler.register("core.info", core_info, callers=frozenset({CALLER_EXTENSION}))
        for name, fn, callers in ASK_REQUEST_HANDLERS:
            handler.register(name, fn, callers=callers)
        manager = ExtensionManager(ctx, handler)  # type: ignore[arg-type]
        ctx.extension_manager = manager
        server = asyncio.create_task(manager.run())
        await _wait_for(lambda: manager.listen_state()["listening"])
        home, home_run = await _connect(workspace, port, tmp_path / "home", ExtensionInfo(name="home", version="1"))
        net_info = ExtensionInfo(name="net", version="1",
                                 offers=ExtensionOffers(knows=[{"method": "net.usage", "name": "Internet use"}]))
        net, net_run = await _connect(workspace, port, tmp_path / "net", net_info)
        net.register_request("net.usage", net_usage)

        with story.begin("page", parent=PARENT):  # HomeHiro's page request
            await home.request("core.info")
            assert await home.ask("net", "net.usage") == {"bytes": 42}
        await home.request("core.info")  # outside any story: the core's handler runs in a story of its own

        for client in (home, net):
            await client.stop()
        ctx.stop_event.set()
        for task in (home_run, net_run, server):
            task.cancel()
        await asyncio.gather(home_run, net_run, server, return_exceptions=True)

    asyncio.run(scenario())
    assert in_core[0] == STORY and in_core[1] not in (None, STORY)
    assert in_net == [STORY]
