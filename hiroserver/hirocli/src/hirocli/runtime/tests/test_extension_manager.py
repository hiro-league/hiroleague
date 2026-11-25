"""End to end: the core's ExtensionManager and the SDK's ExtensionClient.

Runs the real extension socket on a free local port with a temporary workspace,
and the real client against it: pairing with a code, both Phase 3 test calls,
a devices-only method refused, a wrong code, removal, and signing in again.
"""

from __future__ import annotations

import asyncio
import logging
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
from hirocli.domain.extensions import (
    list_paired_extensions,
    load_extension_pairing,
    remove_paired_extension,
    start_extension_pairing,
)
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


def test_a_second_app_with_a_taken_name_is_refused_and_the_code_stays(tmp_path: Path, caplog) -> None:
    """Installing apps, phase 2: one name is one app (a second ``home`` would take HomeHiro's rights, picks and asks).
    The refusal says why in the app, the core logs it, and the code still pairs the app it was made for."""
    caplog.set_level(logging.WARNING)

    async def scenario() -> None:
        workspace = tmp_path / "ws"
        port = _free_port()
        manager, ctx = _core(workspace, port)
        server = asyncio.create_task(manager.run())
        await _wait_for(lambda: manager.listen_state()["listening"])

        home = _client(port, tmp_path / "home")
        runner = asyncio.create_task(home.run())
        home.pair(start_extension_pairing(workspace, code_length=6, ttl_seconds=60).code)
        await _wait_for(lambda: home.status == STATUS_CONNECTED)

        # A second "home" with a good code: refused, in words; its code dropped, nothing stored.
        session = start_extension_pairing(workspace, code_length=6, ttl_seconds=60)
        second = _client(port, tmp_path / "second")
        second_runner = asyncio.create_task(second.run())
        second.pair(session.code)
        await _wait_for(lambda: second.status == STATUS_NOT_PAIRED and "error" in second.status_detail)
        assert "already paired as “home”" in second.status_detail["error"]
        assert [e.name for e in list_paired_extensions(workspace)] == ["home"]
        assert home.status == STATUS_CONNECTED

        # The code wasn't burned: the app it was made for still pairs with it.
        net = ExtensionClient(f"ws://127.0.0.1:{port}", ExtensionInfo(name="net"), ExtensionCredentials(tmp_path / "net"))
        net_runner = asyncio.create_task(net.run())
        net.pair(session.code)
        await _wait_for(lambda: net.status == STATUS_CONNECTED)

        # The core's own name is no app's.
        start_extension_pairing(workspace, code_length=6, ttl_seconds=60)
        core = ExtensionClient(f"ws://127.0.0.1:{port}", ExtensionInfo(name="hiroleague"),
                               ExtensionCredentials(tmp_path / "core"))
        core_runner = asyncio.create_task(core.run())
        core.pair(load_extension_pairing(workspace).code)
        await _wait_for(lambda: core.status == STATUS_NOT_PAIRED and "error" in core.status_detail)
        assert "HiroLeague's own name" in core.status_detail["error"]

        for client, task in ((home, runner), (second, second_runner), (net, net_runner), (core, core_runner)):
            await client.stop()
            await task
        ctx.stop_event.set()
        await asyncio.wait_for(server, 5)

    asyncio.run(scenario())
    refused = [r for r in caplog.records if "Extension refused" in r.getMessage() and "name_taken" in r.getMessage()]
    assert len(refused) == 2 and all(r.levelno == logging.WARNING for r in refused)


def test_a_paired_apps_name_is_fixed_at_pairing(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace = tmp_path / "ws"
        port = _free_port()
        manager, ctx = _core(workspace, port)
        server = asyncio.create_task(manager.run())
        await _wait_for(lambda: manager.listen_state()["listening"])
        clients = []
        for name in ("home", "net"):
            client = ExtensionClient(f"ws://127.0.0.1:{port}", ExtensionInfo(name=name),
                                     ExtensionCredentials(tmp_path / name))
            clients.append((client, asyncio.create_task(client.run())))
            client.pair(start_extension_pairing(workspace, code_length=6, ttl_seconds=60).code)
            await _wait_for(lambda c=client: c.status == STATUS_CONNECTED)
        net, net_runner = clients[1]
        await net.stop()
        await net_runner

        # NetHiro starts again declaring another app's name, then a free one: both refused, and it keeps its key (it
        # is still NetHiro); its record keeps its name.
        for other in ("home", "network"):
            renamed = ExtensionClient(f"ws://127.0.0.1:{port}", ExtensionInfo(name=other),
                                      ExtensionCredentials(tmp_path / "net"))
            renamed_runner = asyncio.create_task(renamed.run())
            await _wait_for(lambda r=renamed: "name is fixed at pairing" in str(r.status_detail.get("error", "")))
            assert f"paired as “net” and now calls itself “{other}”" in renamed.status_detail["error"]
            assert ExtensionCredentials(tmp_path / "net").extension_id() is not None
            assert sorted(e.name for e in list_paired_extensions(workspace)) == ["home", "net"]
            await renamed.stop()
            await renamed_runner

        # Its name back: it connects as before
        back = ExtensionClient(f"ws://127.0.0.1:{port}", ExtensionInfo(name="net"), ExtensionCredentials(tmp_path / "net"))
        back_runner = asyncio.create_task(back.run())
        await _wait_for(lambda: back.status == STATUS_CONNECTED)
        await back.stop()
        await back_runner
        home, home_runner = clients[0]
        await home.stop()
        await home_runner
        ctx.stop_event.set()
        await asyncio.wait_for(server, 5)

    asyncio.run(scenario())


def test_an_app_that_lost_its_key_pairs_again_on_its_own_record(tmp_path: Path) -> None:
    """Pair again: a code made for one paired app; only that app takes it, and its new key goes on its record, so its
    id (and with it its name, rights and AI picks) stays."""

    async def scenario() -> None:
        workspace = tmp_path / "ws"
        port = _free_port()
        manager, ctx = _core(workspace, port)
        server = asyncio.create_task(manager.run())
        await _wait_for(lambda: manager.listen_state()["listening"])

        home = _client(port, tmp_path / "home")
        runner = asyncio.create_task(home.run())
        home.pair(start_extension_pairing(workspace, code_length=6, ttl_seconds=60).code)
        await _wait_for(lambda: home.status == STATUS_CONNECTED)
        await home.stop()
        await runner
        [paired] = list_paired_extensions(workspace)

        # Its data folder was reset: a new key. A code for "home" again; another app can't take it.
        session = start_extension_pairing(workspace, code_length=6, ttl_seconds=60, extension_id=paired.extension_id)
        net = ExtensionClient(f"ws://127.0.0.1:{port}", ExtensionInfo(name="net"), ExtensionCredentials(tmp_path / "net"))
        net_runner = asyncio.create_task(net.run())
        net.pair(session.code)
        await _wait_for(lambda: net.status == STATUS_NOT_PAIRED and "error" in net.status_detail)
        assert "pairs “home” again" in net.status_detail["error"]

        again = _client(port, tmp_path / "home-reset")
        again_runner = asyncio.create_task(again.run())
        again.pair(session.code)
        await _wait_for(lambda: again.status == STATUS_CONNECTED)
        assert ExtensionCredentials(tmp_path / "home-reset").extension_id() == paired.extension_id
        [record] = list_paired_extensions(workspace)
        assert record.extension_id == paired.extension_id and record.public_key != paired.public_key
        assert load_extension_pairing(workspace) is None  # one code, one pairing

        for client, task in ((net, net_runner), (again, again_runner)):
            await client.stop()
            await task
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
