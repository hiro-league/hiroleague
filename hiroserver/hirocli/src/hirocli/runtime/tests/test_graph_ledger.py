from __future__ import annotations

import asyncio
import csv
from pathlib import Path
from typing import Any

import pytest

from hiro_commons.log import Logger
from hirocli.runtime.agent_graph.base import BaseAgentGraph
from hirocli.runtime.agent_graph.ledger import LedgerSink, current_entry, graph_logged


class LedgerProbeGraph(BaseAgentGraph):
    def build(self, **_: Any):
        raise NotImplementedError

    @graph_logged()
    async def ok_node(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}

    @graph_logged()
    async def early_node(self, state: dict[str, Any]) -> dict[str, Any]:
        return {}

    @graph_logged()
    async def error_node(self, state: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("boom")

    @graph_logged()
    async def cancelled_node(self, state: dict[str, Any]) -> dict[str, Any]:
        raise asyncio.CancelledError()

    @graph_logged(flush=False)
    async def child_node(self, state: dict[str, Any]) -> dict[str, Any]:
        entry = current_entry.get()
        assert entry is not None
        child = entry.spawn_child(node="tools/search", elapsed_ms=7)
        child.add_usage(provider="openai", model="openai:gpt-5.4", input_tokens=10)
        child.set_decision("ok", "ok")
        return {}

    @graph_logged()
    async def timing_only_node(self, state: dict[str, Any]) -> dict[str, Any]:
        entry = current_entry.get()
        assert entry is not None
        entry.add_usage(provider="openai", model="openai:gpt-5.4", input_tokens=10)
        entry.set_decision("text_reply", "ok")
        return {}


@pytest.fixture(autouse=True)
def _setup_logger() -> None:
    LedgerSink._opened.clear()
    Logger.set_level("INFO")
    Logger.setup(console=False)
    yield
    LedgerSink._opened.clear()


@pytest.mark.asyncio
async def test_ledger_wrapper_writes_ok_and_resets_context(tmp_path: Path) -> None:
    graph = _graph(tmp_path)

    await graph.ok_node(_state("in-ok"))

    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["run_id"] == "chat-in-ok"
    assert rows[0]["node"] == "ok"
    assert rows[0]["status"] == "ok"
    assert current_entry.get() is None


@pytest.mark.asyncio
async def test_ledger_wrapper_writes_error_cancelled_and_early_return(tmp_path: Path) -> None:
    graph = _graph(tmp_path)

    await graph.early_node(_state("in-early"))
    with pytest.raises(ValueError):
        await graph.error_node(_state("in-error"))
    with pytest.raises(asyncio.CancelledError):
        await graph.cancelled_node(_state("in-cancel"))

    rows = _rows(tmp_path)
    by_node = {row["node"]: row for row in rows}
    assert by_node["early"]["status"] == "ok"
    assert by_node["error"]["status"] == "error"
    assert by_node["error"]["error_code"] == "value"
    assert by_node["cancelled"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_ledger_spawn_child_writes_sibling_row_without_parent(tmp_path: Path) -> None:
    graph = _graph(tmp_path)

    await graph.child_node(_state("in-child"))

    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["node"] == "tools/search"
    assert rows[0]["run_id"] == "chat-in-child"
    assert rows[0]["decision_kind"] == "ok"
    assert rows[0]["model"] == ""
    assert rows[0]["input_tokens"] == ""


@pytest.mark.asyncio
async def test_ledger_tracks_node_attempts_and_honors_captures(tmp_path: Path) -> None:
    graph = _graph(tmp_path)

    await graph.ok_node(_state("in-attempt"))
    await graph.ok_node(_state("in-attempt"))
    await graph.timing_only_node(_state("in-captures"))

    rows = _rows(tmp_path)
    ok_rows = [row for row in rows if row["node"] == "ok"]
    assert [row["node_attempt"] for row in ok_rows] == ["1", "2"]
    timing_row = [row for row in rows if row["node"] == "timing_only"][0]
    assert timing_row["model"] == ""
    assert timing_row["input_tokens"] == ""
    assert timing_row["decision_kind"] == ""


@pytest.mark.asyncio
async def test_ledger_tracking_is_bounded_per_sink(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    graph._ledger_sink._max_tracked_runs = 2

    await graph.ok_node(_state("in-one"))
    await graph.ok_node(_state("in-two"))
    await graph.ok_node(_state("in-three"))

    assert list(graph._ledger_sink._step_indexes) == ["chat-in-two", "chat-in-three"]
    assert len(graph._ledger_sink._attempt_indexes) == 2


@pytest.mark.asyncio
async def test_send_branch_identity_and_caught_error_status(tmp_path: Path) -> None:
    graph = _graph(tmp_path)

    await graph.stt_node(
        {
            "audio_item": {"item_index": 3, "body": "", "mime_type": "audio/m4a"},
            "inbound_id": "in-send",
            "chat_channel_id": 7,
            "character_id": "hiro",
            "routing_metadata": {"device_id": "dev-1", "user_id": "user-1"},
        },
        lambda _event: None,
    )

    row = _rows(tmp_path)[0]
    assert row["status"] == "error"
    assert row["branch_index"] == "3"
    assert row["character_id"] == "hiro"
    assert row["device_id"] == "dev-1"
    assert row["user_id"] == "user-1"


@pytest.mark.asyncio
async def test_skipped_node_preserves_skipped_status(tmp_path: Path) -> None:
    graph = _graph(tmp_path)

    await graph.tts_node(
        {
            "inbound_id": "in-tts-skip",
            "chat_channel_id": 7,
            "reply_text": "",
            "character_id": "hiro",
        },
        lambda _event: None,
    )

    row = _rows(tmp_path)[0]
    assert row["node"] == "tts"
    assert row["status"] == "skipped"
    assert row["decision_kind"] == "skipped_no_text"


def _graph(tmp_path: Path) -> LedgerProbeGraph:
    return LedgerProbeGraph(
        workspace_path=tmp_path,
        stt_service=None,
        vision_service=None,
        tts_service=None,
        credential_store=None,
        checkpointer=None,
    )


def test_stt_usage_does_not_get_token_priced(tmp_path: Path) -> None:
    graph = _graph(tmp_path)

    priced = graph._ledger_sink._with_cost(
        {
            "provider": "openai",
            "model": "openai:gpt-4o-transcribe",
            "stt_audio_seconds": 12.5,
        }
    )

    assert priced["cost_usd"] == ""
    assert priced["pricing_version"] == ""


def test_tts_audio_seconds_are_persisted(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    entry = graph._ledger_sink.open_entry(
        "tts",
        _state("in-tts"),
        captures=frozenset({"usage"}),
    )
    entry.add_usage(
        provider="openai",
        model="openai:gpt-4o-mini-tts",
        input_tokens=5,
        tts_chars=25,
        tts_audio_seconds=2.5,
    )

    graph._ledger_sink.write_rows(entry.rows(include_parent=True))

    row = _rows(tmp_path)[0]
    assert row["tts_audio_seconds"] == "2.5"


def _state(inbound_id: str) -> dict[str, Any]:
    return {
        "inbound_id": inbound_id,
        "chat_channel_id": 5,
        "character_id": "hiro",
        "model_id": "openai:gpt-5.4",
    }


def _rows(tmp_path: Path) -> list[dict[str, str]]:
    path = tmp_path / "logs" / "graph.log"
    assert path.exists()
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))
