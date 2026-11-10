"""Phase 9b: extensions ask each other through the core, only for methods the asked one offers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from hiro_channel_sdk.constants import ASK_ERROR_NOT_OFFERED, ASKED_BY
from hiro_channel_sdk.extension import ExtensionRequestError

from hirocli.domain.extensions import add_paired_extension
from hirocli.runtime.asks_between_extensions import handle_extensions_ask, offered_methods
from hirocli.runtime.request_handler import RequestRefused

NET_INFO = {"name": "net", "offers": {"knows": [{"method": "net.person_usage", "name": "A person's internet use"}]}}


class FakeManager:
    def __init__(self, live: dict[str, dict[str, Any]], answer: Any = None) -> None:
        self.live = live
        self.answer = answer
        self.asked: list[tuple[str, str, dict[str, Any], float]] = []

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return self.live

    async def request(self, extension_id: str, method: str, params: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        self.asked.append((extension_id, method, params, timeout))
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


def _ctx(workspace: Path, manager: FakeManager) -> SimpleNamespace:
    home = add_paired_extension(workspace, name="home", public_key="k", info={"name": "home"})
    return SimpleNamespace(
        server_ctx=SimpleNamespace(workspace_path=workspace, extension_manager=manager),
        workspace_path=workspace,
        msg=SimpleNamespace(routing=SimpleNamespace(sender_id=home.extension_id)),
    )


def test_offered_methods_come_from_knows_and_can_do() -> None:
    info = {"offers": {"knows": [{"method": "a.x"}, {"name": "no method"}], "can_do": [{"method": "a.y"}], "shows": [{"method": "z"}]}}
    assert offered_methods(info) == {"a.x", "a.y"}
    assert offered_methods({}) == set()


def test_an_ask_is_passed_on_with_who_asked(tmp_path: Path) -> None:
    manager = FakeManager({"ext-net": {"name": "net", "info": NET_INFO}}, answer={"bytes": 42})
    answer = asyncio.run(handle_extensions_ask(
        {"to": "net", "method": "net.person_usage", "params": {"person_id": "p1"}, "timeout": 500}, _ctx(tmp_path, manager)))
    assert answer == {"bytes": 42}
    extension_id, method, params, timeout = manager.asked[0]
    assert (extension_id, method, params[ASKED_BY], params["person_id"]) == ("ext-net", "net.person_usage", "home", "p1")
    assert timeout == 60.0  # capped


@pytest.mark.parametrize(("live", "params", "code"), [
    ({}, {"to": "net", "method": "net.person_usage"}, "not_connected"),
    ({"ext-net": {"name": "net", "info": NET_INFO}}, {"to": "net", "method": "net.secrets"}, ASK_ERROR_NOT_OFFERED),
    ({}, {"to": "home", "method": "x"}, "invalid_params"),  # asking itself
    ({}, {"method": "x"}, "invalid_params"),
])
def test_an_ask_is_refused_with_a_reason(tmp_path: Path, live, params, code) -> None:
    with pytest.raises(RequestRefused) as refused:
        asyncio.run(handle_extensions_ask(params, _ctx(tmp_path, FakeManager(live))))
    assert refused.value.code == code


def test_the_asked_extensions_error_goes_back_as_it_is(tmp_path: Path) -> None:
    manager = FakeManager({"ext-net": {"name": "net", "info": NET_INFO}},
                          answer=ExtensionRequestError("unknown_person", "No such person."))
    with pytest.raises(RequestRefused) as refused:
        asyncio.run(handle_extensions_ask({"to": "net", "method": "net.person_usage"}, _ctx(tmp_path, manager)))
    assert (refused.value.code, refused.value.message) == ("unknown_person", "No such person.")
