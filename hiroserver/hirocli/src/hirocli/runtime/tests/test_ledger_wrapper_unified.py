"""Unified wrapper matrix — bound/free × sync/async × ok/cancel/error (P1b)."""

from __future__ import annotations

import asyncio
import csv
from pathlib import Path
from typing import Any

import pytest

from hiro_commons.log import Logger
from hirocli.runtime.agent_graph.ledger import LedgerSink, graph_logged
from hirocli.runtime.agent_graph.ledger.wrapper import wrap_graph_callable, wrap_graph_node
from hirocli.runtime.tests.graph_fakes import make_agent_services


class _Owner:
    def __init__(self, sink: LedgerSink) -> None:
        self._ledger_sink = sink


@pytest.fixture(autouse=True)
def _ledger_logger_setup() -> None:
    LedgerSink._opened.clear()
    Logger.set_level("INFO")
    Logger.setup(console=False)
    yield
    LedgerSink._opened.clear()


def _rows(tmp_path: Path) -> list[dict[str, str]]:
    path = tmp_path / "logs" / "graph.log"
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _state() -> dict[str, Any]:
    return {"inbound_id": "in-wrap", "chat_channel_id": 1, "character_id": "hiro"}


@pytest.mark.parametrize(
    ("outcome", "expected_status", "exc"),
    [
        ("ok", "ok", None),
        ("cancelled", "cancelled", asyncio.CancelledError()),
        ("error", "error", ValueError("boom")),
    ],
)
@pytest.mark.asyncio
async def test_bound_async_wrapper_outcomes(
    tmp_path: Path,
    outcome: str,
    expected_status: str,
    exc: BaseException | None,
) -> None:
    owner = _Owner(LedgerSink(tmp_path))

    class Nodes(_Owner):
        @graph_logged()
        async def probe_node(self, state: dict[str, Any]) -> dict[str, Any]:
            if exc is not None:
                raise exc
            return {"ok": True}

    node = wrap_graph_node("probe", Nodes.probe_node)

    if exc is None:
        await node(owner, _state())
    elif isinstance(exc, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await node(owner, _state())
    else:
        with pytest.raises(ValueError):
            await node(owner, _state())

    assert _rows(tmp_path)[0]["status"] == expected_status


@pytest.mark.parametrize(
    ("outcome", "expected_status", "exc"),
    [
        ("ok", "ok", None),
        ("cancelled", "cancelled", asyncio.CancelledError()),
        ("error", "error", ValueError("boom")),
    ],
)
def test_bound_sync_wrapper_outcomes(
    tmp_path: Path,
    outcome: str,
    expected_status: str,
    exc: BaseException | None,
) -> None:
    owner = _Owner(LedgerSink(tmp_path))

    class Nodes(_Owner):
        @graph_logged()
        def probe_node(self, state: dict[str, Any]) -> dict[str, Any]:
            if exc is not None:
                raise exc
            return {"ok": True}

    node = wrap_graph_node("probe", Nodes.probe_node)

    if exc is None:
        node(owner, _state())
    elif isinstance(exc, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            node(owner, _state())
    else:
        with pytest.raises(ValueError):
            node(owner, _state())

    assert _rows(tmp_path)[0]["status"] == expected_status


@pytest.mark.parametrize(
    ("outcome", "expected_status", "exc"),
    [
        ("ok", "ok", None),
        ("cancelled", "cancelled", asyncio.CancelledError()),
        ("error", "error", ValueError("boom")),
    ],
)
@pytest.mark.asyncio
async def test_plain_async_wrapper_outcomes(
    tmp_path: Path,
    outcome: str,
    expected_status: str,
    exc: BaseException | None,
) -> None:
    owner = _Owner(LedgerSink(tmp_path))

    @graph_logged()
    async def probe(state: dict[str, Any]) -> dict[str, Any]:
        if exc is not None:
            raise exc
        return {"ok": True}

    fn = wrap_graph_callable(owner, "plain_probe", probe)

    if exc is None:
        await fn(_state())
    elif isinstance(exc, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await fn(_state())
    else:
        with pytest.raises(ValueError):
            await fn(_state())

    assert _rows(tmp_path)[0]["status"] == expected_status


@pytest.mark.parametrize(
    ("outcome", "expected_status", "exc"),
    [
        ("ok", "ok", None),
        ("cancelled", "cancelled", asyncio.CancelledError()),
        ("error", "error", ValueError("boom")),
    ],
)
def test_plain_sync_wrapper_outcomes(
    tmp_path: Path,
    outcome: str,
    expected_status: str,
    exc: BaseException | None,
) -> None:
    owner = _Owner(LedgerSink(tmp_path))

    @graph_logged()
    def probe(state: dict[str, Any]) -> dict[str, Any]:
        if exc is not None:
            raise exc
        return {"ok": True}

    fn = wrap_graph_callable(owner, "plain_probe", probe)

    if exc is None:
        fn(_state())
    elif isinstance(exc, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            fn(_state())
    else:
        with pytest.raises(ValueError):
            fn(_state())

    assert _rows(tmp_path)[0]["status"] == expected_status


@pytest.mark.asyncio
async def test_wrapper_no_sink_passthrough() -> None:
    owner = _Owner.__new__(_Owner)
    owner._ledger_sink = None

    @graph_logged()
    async def probe(state: dict[str, Any]) -> dict[str, Any]:
        return {"seen": state["inbound_id"]}

    fn = wrap_graph_callable(owner, "plain_probe", probe)
    assert (await fn(_state())) == {"seen": "in-wrap"}
