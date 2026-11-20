"""logs.send: an app's log lines into the core's log store, under the name the core knows it by."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from hiro_channel_sdk.constants import METHOD_LOGS_SEND

from hirocli.runtime.logs_for_extensions import handle_logs_send
from hirocli.runtime.request_handler import EXTENSIONS_ONLY, RequestRefused
from hirocli.runtime.request_methods import _REGISTERED_HANDLERS
from hirocli.services import log_store


class FakeExtensions:
    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {"ext-home": {"name": "home"}}


def _ctx(workspace: Path) -> SimpleNamespace:
    server_ctx = SimpleNamespace(workspace_path=workspace, extension_manager=FakeExtensions())
    return SimpleNamespace(server_ctx=server_ctx, msg=SimpleNamespace(routing=SimpleNamespace(sender_id="ext-home")))


@pytest.fixture
def store(tmp_path: Path):
    s = log_store.start(tmp_path / "logs")
    yield s
    log_store.stop()


def _line(body: str) -> str:
    return json.dumps({"Timestamp": "2026-11-20T10:00:00Z", "SeverityText": "INFO", "SeverityNumber": 9,
                       "Body": body, "InstrumentationScope": "homehiro.ha", "Resource": {"service.name": "home"}})


def test_an_apps_lines_land_in_its_stream_once(tmp_path: Path, store) -> None:
    params = {"lines": [["2026-11-20:100", _line("one")], ["2026-11-20:200", _line("two")]]}
    assert asyncio.run(handle_logs_send(params, _ctx(tmp_path))) == {"last": "2026-11-20:200"}
    assert asyncio.run(handle_logs_send(params, _ctx(tmp_path))) == {"last": "2026-11-20:200"}  # sent again
    (path,) = (tmp_path / "logs").glob("app-home-*.jsonl")
    assert [json.loads(x)["Body"] for x in path.read_text(encoding="utf-8").splitlines()] == ["one", "two"]


def test_a_batch_that_isnt_one_is_refused(tmp_path: Path, store) -> None:
    with pytest.raises(RequestRefused):
        asyncio.run(handle_logs_send({"lines": "nope"}, _ctx(tmp_path)))


def test_extensions_only() -> None:
    callers = {method: who for method, _handler, who in _REGISTERED_HANDLERS}
    assert callers[METHOD_LOGS_SEND] == EXTENSIONS_ONLY
