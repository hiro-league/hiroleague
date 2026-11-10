"""extensions.list: every paired extension and its repo, for the code reports."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hiro_channel_sdk import ExtensionInfo
from hiro_channel_sdk.constants import CORE_REPO, METHOD_EXTENSIONS_LIST

from hirocli.domain.extensions import add_paired_extension
from hirocli.runtime.extensions_for_extensions import handle_extensions_list
from hirocli.runtime.request_handler import EXTENSIONS_ONLY
from hirocli.runtime.request_methods import _REGISTERED_HANDLERS, handle_core_info


class FakeExtensions:
    def __init__(self, live: dict[str, dict[str, Any]]) -> None:
        self.live = live

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return self.live


def _ctx(workspace: Path, manager: Any = None) -> SimpleNamespace:
    server_ctx = SimpleNamespace(
        workspace_path=workspace,
        extension_manager=manager,
        workspace_name="default",
        config=SimpleNamespace(admin_port=18083),
    )
    return SimpleNamespace(server_ctx=server_ctx, msg=SimpleNamespace(routing=SimpleNamespace(sender_id="ext-reports")))


def test_every_paired_extension_with_its_repo(tmp_path: Path) -> None:
    home = add_paired_extension(
        tmp_path, name="home", public_key="k1", info=ExtensionInfo(name="home", version="0.1.0", repo="homehiro").model_dump()
    )
    reports = add_paired_extension(tmp_path, name="reports", public_key="k2", info={"name": "reports", "version": "0.1.0"})
    # HomeHiro is connected and now says a newer version; the reports are not connected and said no repo.
    live = {home.extension_id: {"name": "home", "info": {"name": "home", "version": "0.2.0", "repo": "homehiro"}}}
    answer = asyncio.run(handle_extensions_list({}, _ctx(tmp_path, FakeExtensions(live))))
    assert answer["extensions"] == [
        {"extension_id": home.extension_id, "name": "home", "version": "0.2.0", "description": "", "repo": "homehiro", "connected": True},
        {"extension_id": reports.extension_id, "name": "reports", "version": "0.1.0", "description": "", "repo": "", "connected": False},
    ]


def test_no_extensions_yet(tmp_path: Path) -> None:
    assert asyncio.run(handle_extensions_list({}, _ctx(tmp_path))) == {"extensions": []}


def test_extensions_only_and_the_core_names_its_repo(tmp_path: Path) -> None:
    callers = {method: who for method, _handler, who in _REGISTERED_HANDLERS}
    assert callers[METHOD_EXTENSIONS_LIST] == EXTENSIONS_ONLY
    assert asyncio.run(handle_core_info({}, _ctx(tmp_path)))["repo"] == CORE_REPO == "hiroleague"


def test_an_extension_says_its_repo() -> None:
    assert ExtensionInfo(name="home").repo == ""
    assert ExtensionInfo(name="home", repo="homehiro").model_dump()["repo"] == "homehiro"
